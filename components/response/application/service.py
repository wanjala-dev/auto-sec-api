"""ResponseActionService — the response context's single application front door.

The controller and the agent tool call this, never the individual use cases or
adapters. It holds the wired use cases + the store (for reads) so callers get one
coherent surface for the whole propose → approve → reject → rollback lifecycle.
"""

from __future__ import annotations

from uuid import UUID

from components.response.application.use_cases.approve_response_action_use_case import (
    ApproveResponseActionUseCase,
)
from components.response.application.use_cases.propose_response_action_use_case import (
    ProposeResponseActionUseCase,
)
from components.response.application.use_cases.reject_response_action_use_case import (
    RejectResponseActionUseCase,
)
from components.response.application.use_cases.rollback_response_action_use_case import (
    RollbackResponseActionUseCase,
)
from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec


class ResponseActionService:
    def __init__(
        self,
        *,
        propose: ProposeResponseActionUseCase,
        approve: ApproveResponseActionUseCase,
        reject: RejectResponseActionUseCase,
        rollback: RollbackResponseActionUseCase,
        store,
    ) -> None:
        self._propose = propose
        self._approve = approve
        self._reject = reject
        self._rollback = rollback
        self._store = store

    def propose(
        self,
        *,
        workspace_id: UUID,
        finding_fingerprint: str,
        spec: ResponseActionSpec,
        requested_by: str,
        dry_run: bool,
        validate_live: bool = True,
    ) -> ResponseActionExecution:
        return self._propose.execute(
            workspace_id=workspace_id,
            finding_fingerprint=finding_fingerprint,
            spec=spec,
            requested_by=requested_by,
            dry_run=dry_run,
            validate_live=validate_live,
        )

    def approve(
        self, *, action_id: UUID, workspace_id: UUID, approver_id: str, justification: str
    ) -> ResponseActionExecution:
        return self._approve.execute(
            action_id=action_id,
            workspace_id=workspace_id,
            approver_id=approver_id,
            justification=justification,
        )

    def reject(self, *, action_id: UUID, workspace_id: UUID, actor_id: str, note: str = "") -> ResponseActionExecution:
        return self._reject.execute(action_id=action_id, workspace_id=workspace_id, actor_id=actor_id, note=note)

    def rollback(self, *, action_id: UUID, workspace_id: UUID, actor_id: str) -> ResponseActionExecution:
        return self._rollback.execute(action_id=action_id, workspace_id=workspace_id, actor_id=actor_id)

    def get(self, *, action_id: UUID, workspace_id: UUID) -> ResponseActionExecution | None:
        return self._store.get(action_id, workspace_id=workspace_id)

    def list_for_workspace(
        self, *, workspace_id: UUID, status: str | None = None, limit: int = 50
    ) -> list[ResponseActionExecution]:
        return self._store.list_for_workspace(workspace_id, status=status, limit=limit)

    def list_pending(self, *, workspace_id: UUID, limit: int = 50) -> list[ResponseActionExecution]:
        return self._store.list_for_workspace(workspace_id, status=ExecutionStatus.PROPOSED.value, limit=limit)
