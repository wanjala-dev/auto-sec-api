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
    def __init__(self, *, store: FindingStorePort) -> None:
        self._store = store

    def execute(self, command: ChangeFindingStatusCommand) -> ChangeFindingStatusResult:
        if command.action not in VALID_ACTIONS:
            raise InvalidFindingActionError(
                f"Unknown finding action {command.action!r}; expected one of {sorted(VALID_ACTIONS)}."
            )

        existing = self._store.find_by_id(command.workspace_id, command.finding_id)
        if existing is None:
            raise FindingNotFoundError(f"Finding {command.finding_id} not found in workspace {command.workspace_id}.")

        updated = self._transition(existing, command)
        if updated.status == existing.status:
            # Idempotent no-op (e.g. resolving an already-resolved finding) — nothing to write.
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
        return ChangeFindingStatusResult(finding_id=updated.id, status=updated.status.value, changed=True)

    @staticmethod
    def _transition(finding: FindingEntity, command: ChangeFindingStatusCommand) -> FindingEntity:
        if command.action == RESOLVE:
            return finding.resolved(at=command.at)
        if command.action == SUPPRESS:
            return finding.suppressed(at=command.at)
        if command.action == REOPEN:
            return finding.reopened()
        # Unreachable — action was validated above; kept exhaustive for safety.
        raise InvalidFindingActionError(command.action)
