"""RecordRemediationEntryUseCase — the SOLE creator of a RemediationEntry.

This use case IS the D1 entry-gate (ADR 0012). It is the *only* code path that
constructs and persists a ``RemediationEntry``; there is no controller create
endpoint, no admin add, no repository write reachable from anywhere else. That
single-writer property is the security control — it structurally denies RAG
poisoning, because corpus membership cannot be *asserted*, only *earned* by
clearing all three conditions.

Defense in depth: the use case NEVER trusts the caller's claims. It independently
re-gathers the three facts through read-ports and re-evaluates the gate itself:

  (a) sign-off APPROVED   — via ``SignOffGatePort`` (delegates to sign_off's
      application surface; fail-closed if unregistered/not approved).
  (b) draft PR APPLIED    — the caller must explicitly confirm ``pr_applied``
      (merge-detection is not built — P4), AND a draft PR must actually exist on
      the finding, AND the confirmed applied URL must match it. "A draft PR is
      open" is NOT "the fix was applied".
  (c) finding RESOLVED    — via ``FindingRemediationFactsPort`` reading the
      finding/board state.

If any condition is missing, it RAISES ``EntryGateNotSatisfiedError`` and writes
nothing. Idempotent: a fix that already cleared the gate returns the existing
entry rather than creating a duplicate.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.ports.finding_remediation_facts_port import (
    FindingRemediationFactsPort,
)
from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.services.entry_gate_policy import EntryGatePolicy
from components.remediation.domain.services.remediation_ranking_policy import (
    RemediationRankingPolicy,
)
from components.remediation.domain.value_objects.gate_conditions import GateConditions

logger = logging.getLogger(__name__)


class RecordRemediationEntryUseCase:
    def __init__(
        self,
        *,
        store: RemediationEntryStorePort,
        sign_off_gate: SignOffGatePort,
        finding_facts: FindingRemediationFactsPort,
        on_admit: Callable[[RemediationEntry], None] | None = None,
    ) -> None:
        self._store = store
        self._sign_off_gate = sign_off_gate
        self._finding_facts = finding_facts
        # Fired ONCE per NEW admission (never on an idempotent hit) — the precise
        # moment novelty is known. The provider wires outcome propagation here (P5);
        # left None it is a no-op, so the gate's core stays independently testable.
        self._on_admit = on_admit

    def execute(self, command: RecordRemediationEntryCommand) -> RemediationEntry:
        workspace_id = command.workspace_id

        # Idempotency: one entry per fix. If this finding already cleared the
        # gate, return the existing entry — never create a duplicate.
        existing = self._store.find_by_finding_task(workspace_id=workspace_id, finding_task_id=command.finding_task_id)
        if existing is not None:
            logger.info(
                "remediation_entry_gate idempotent_hit workspace_id=%s finding_task_id=%s entry_id=%s",
                workspace_id,
                command.finding_task_id,
                existing.id,
            )
            return existing

        # (b/c) Re-gather the finding facts ourselves — never trust the caller.
        facts = self._finding_facts.get_facts(workspace_id=str(workspace_id), finding_task_id=command.finding_task_id)

        # (a) sign-off approved — fail-closed.
        approved = self._sign_off_gate.is_approved(
            artifact_type=command.sign_off_artifact_type,
            artifact_id=command.sign_off_artifact_id,
        )

        # (b) PR applied — requires the explicit operator confirmation AND a real
        # opened draft PR AND the confirmed URL matching it. Merge-detection is
        # not built (P4), so we refuse to *infer* applied from an open draft PR.
        applied = bool(
            command.pr_applied
            and facts.exists
            and facts.draft_pr_url
            and command.applied_pr_url
            and command.applied_pr_url == facts.draft_pr_url
        )

        # (c) finding resolved.
        resolved = bool(facts.exists and facts.finding_resolved)

        conditions = GateConditions(
            sign_off_approved=approved,
            draft_pr_applied=applied,
            finding_resolved=resolved,
        )

        # THE GATE. Raises EntryGateNotSatisfiedError → nothing is written.
        if not conditions.satisfied:
            logger.warning(
                "remediation_entry_gate refused workspace_id=%s finding_task_id=%s unmet=%s",
                workspace_id,
                command.finding_task_id,
                ",".join(conditions.unmet_reasons()),
            )
            EntryGatePolicy.enforce(conditions)  # raises

        entry = RemediationEntry(
            id=uuid4(),
            workspace_id=workspace_id,
            finding_kind=facts.finding_kind,
            source_type=facts.source_type,
            tags=tuple(command.tags),
            language=command.language,
            code=command.code,
            title=command.title,
            summary=command.summary,
            finding_task_id=command.finding_task_id,
            finding_fingerprint=facts.finding_fingerprint,
            provenance_event_ref=facts.provenance_event_ref,
            applied_pr_url=command.applied_pr_url,
            approved_by=command.sign_off_artifact_id,
            resolved_at=datetime.now(UTC),
            # Baseline rating — DERIVED (never caller-set), so every vetted entry
            # starts at the same gate-earned score and only outcomes move it (P5).
            score=RemediationRankingPolicy.derive_score(reuse_count=0, success_count=0, recurrence_count=0),
        )
        saved = self._store.save(entry)
        logger.info(
            "remediation_entry_gate admitted workspace_id=%s finding_task_id=%s entry_id=%s finding_kind=%s",
            workspace_id,
            command.finding_task_id,
            saved.id,
            saved.finding_kind,
        )
        self._notify_admitted(saved)
        return saved

    def _notify_admitted(self, entry: RemediationEntry) -> None:
        """Fire the post-admission hook (outcome propagation, P5). A hook failure
        must NEVER roll back a valid admission — the entry is already saved — so it
        is logged and swallowed."""
        if self._on_admit is None:
            return
        try:
            self._on_admit(entry)
        except Exception:
            logger.exception(
                "remediation_on_admit_hook_failed entry_id=%s workspace_id=%s",
                entry.id,
                entry.workspace_id,
            )
