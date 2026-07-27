"""ResponseActionExecution — the reversible-action aggregate + audit ledger row.

This is the SSOT for a single response action's whole life: what was proposed
(``spec``), how to undo it (``inverse_spec``, computed at propose time so the
rollback never has to re-derive it), who decided what and when, whether it was a
dry-run, and the provider's result. Every human decision returns a *new* frozen
entity (the lifecycle methods below) — the repository persists the transition.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.response.domain.errors import IllegalTransitionError
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec


@dataclass(frozen=True)
class ResponseActionExecution:
    id: UUID
    workspace_id: UUID
    # What this action remediates — the finding it was proposed from.
    finding_fingerprint: str
    spec: ResponseActionSpec
    inverse_spec: ResponseActionSpec
    status: ExecutionStatus
    dry_run: bool
    # Who proposed it (the agent's run principal or an operator) + when.
    requested_by: str
    requested_at: datetime
    # Decision + execution bookkeeping (populated as the lifecycle advances).
    justification: str = ""
    decided_by: str | None = None
    decided_at: datetime | None = None
    executed_at: datetime | None = None
    execution_detail: dict = field(default_factory=dict)
    rolled_back_at: datetime | None = None
    rollback_detail: dict = field(default_factory=dict)
    error: str | None = None

    # ── lifecycle transitions (return a new entity; never mutate) ─────────────

    def approved(self, *, decided_by: str, decided_at: datetime, justification: str) -> ResponseActionExecution:
        self._guard("approve", self.status.can_approve)
        return dataclasses.replace(
            self,
            status=ExecutionStatus.EXECUTED,
            decided_by=decided_by,
            decided_at=decided_at,
            justification=justification,
        )

    def with_execution_result(
        self, *, executed_at: datetime, detail: dict, failed: bool, error: str | None
    ) -> ResponseActionExecution:
        """Stamp the outcome of the cloud call made during approval. A failure
        moves the action to FAILED (approved + attempted, cloud errored)."""
        return dataclasses.replace(
            self,
            status=ExecutionStatus.FAILED if failed else self.status,
            executed_at=executed_at,
            execution_detail=detail,
            error=error,
        )

    def rejected(self, *, decided_by: str, decided_at: datetime, note: str) -> ResponseActionExecution:
        self._guard("reject", self.status.can_reject)
        return dataclasses.replace(
            self,
            status=ExecutionStatus.REJECTED,
            decided_by=decided_by,
            decided_at=decided_at,
            justification=note,
        )

    def rolled_back(self, *, rolled_back_at: datetime, detail: dict) -> ResponseActionExecution:
        self._guard("rollback", self.status.can_rollback)
        return dataclasses.replace(
            self,
            status=ExecutionStatus.ROLLED_BACK,
            rolled_back_at=rolled_back_at,
            rollback_detail=detail,
        )

    def _guard(self, decision: str, allowed: bool) -> None:
        if not allowed:
            raise IllegalTransitionError(str(self.id), self.status.value, decision)
