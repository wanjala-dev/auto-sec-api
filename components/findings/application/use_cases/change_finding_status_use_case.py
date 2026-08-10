"""Operator-driven finding lifecycle transition — the write behind the HUD action row.

The read API (``FindingListView``) makes the SSOT visible; this is the thin, membership-
gated WRITE that lets an operator *act* on a finding without leaving the callout:

- ``resolve``  → RESOLVED (remediated / no longer a concern),
- ``suppress`` → SUPPRESSED (accepted risk / false positive — the finding-native soft
  "delete": the row is retained + auditable, it just drops off the open surfaces),
- ``reopen``   → OPEN (undo a mistaken resolve/dismiss).

No hard delete: findings carry a lifecycle (ADR 0004 D1), so an operator *transitions*
a finding, never destroys the record — a re-observation of a still-present misconfig
reopens a terminal finding on its own. Framework-free: depends only on ``FindingStorePort``.
"""

from __future__ import annotations

import logging

from components.findings.application.commands.change_finding_status_command import (
    REOPEN,
    RESOLVE,
    SUPPRESS,
    VALID_ACTIONS,
    ChangeFindingStatusCommand,
    ChangeFindingStatusResult,
)
from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.domain.errors import (
    FindingNotFoundError,
    InvalidFindingActionError,
)

logger = logging.getLogger(__name__)


class ChangeFindingStatusUseCase:
    def __init__(self, *, store: FindingStorePort, event_publisher=None) -> None:
        self._store = store
        # Duck-typed ``publish`` (same contract as RecordObservedFindingUseCase);
        # optional so a mis-wired publisher can never break the status write.
        self._publisher = event_publisher

    def execute(self, command: ChangeFindingStatusCommand) -> ChangeFindingStatusResult:
        if command.action not in VALID_ACTIONS:
            raise InvalidFindingActionError(
                f"Unknown finding action {command.action!r}; expected one of {sorted(VALID_ACTIONS)}."
            )
        if command.action != SUPPRESS and (command.reason or command.expires_at is not None):
            # Risk-acceptance context is suppress-only (ADR 0015 D9).
            raise InvalidFindingActionError("reason/expires_at are only valid with action='suppress'.")

        existing = self._store.find_by_id(command.workspace_id, command.finding_id)
        if existing is None:
            raise FindingNotFoundError(f"Finding {command.finding_id} not found in workspace {command.workspace_id}.")

        updated = self._transition(existing, command)
        if (
            updated.status == existing.status
            and updated.status_reason == existing.status_reason
            and updated.suppress_expires_at == existing.suppress_expires_at
        ):
            # Idempotent no-op (e.g. resolving an already-resolved finding) — nothing to
            # write. Re-suppressing with a NEW reason/expiry IS a write (it updates the
            # risk-acceptance context, ADR 0015 D9).
            return ChangeFindingStatusResult(finding_id=existing.id, status=existing.status.value, changed=False)

        self._store.upsert(updated)
        logger.info(
            "finding_status_changed workspace_id=%s finding_id=%s action=%s status=%s actor_id=%s",
            command.workspace_id,
            command.finding_id,
            command.action,
            updated.status.value,
            command.actor_id,
        )
        self._publish_terminal_transition(updated, command)
        return ChangeFindingStatusResult(finding_id=updated.id, status=updated.status.value, changed=True)

    def _publish_terminal_transition(self, updated: FindingEntity, command: ChangeFindingStatusCommand) -> None:
        """Best-effort ``FindingResolved`` emission on a terminal transition.

        ``FindingResolved`` is the shared-kernel "this finding reached a terminal
        state (resolved or suppressed)" signal — its documented purpose is that
        consumers can close/archive a board card. The suppress path carries
        ``reason="suppressed"`` so the agents board handler auto-archives the
        card (Henry's 2026-08-09 ruling); the resolve path carries
        ``reason="resolved"``. REOPEN publishes nothing — there is no
        ``FindingReopened`` event today, so an un-suppress does NOT auto-restore
        the card (operator restores from the RECYCLE BIN tray; see the handler's
        docstring). A publish failure is logged, never raised — the status
        change is the fact, the event a side-effect.
        """
        if self._publisher is None or command.action not in (RESOLVE, SUPPRESS):
            return
        try:
            from components.shared_kernel.domain.events import FindingResolved

            self._publisher.publish(
                FindingResolved(
                    workspace_id=command.workspace_id,
                    finding_id=updated.id,
                    fingerprint=updated.fingerprint,
                    reason="suppressed" if command.action == SUPPRESS else "resolved",
                )
            )
        except Exception:
            logger.exception(
                "finding_resolved_event_publish_failed workspace_id=%s finding_id=%s action=%s",
                command.workspace_id,
                command.finding_id,
                command.action,
            )

    @staticmethod
    def _transition(finding: FindingEntity, command: ChangeFindingStatusCommand) -> FindingEntity:
        if command.action == RESOLVE:
            return finding.resolved(at=command.at)
        if command.action == SUPPRESS:
            return finding.suppressed(at=command.at, reason=command.reason, expires_at=command.expires_at)
        if command.action == REOPEN:
            return finding.reopened()
        # Unreachable — action was validated above; kept exhaustive for safety.
        raise InvalidFindingActionError(command.action)
