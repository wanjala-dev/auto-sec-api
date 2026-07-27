"""Output DTO — a ResponseActionExecution entity projected for the HUD/API."""

from __future__ import annotations

from components.response.domain.entities.response_action_entity import ResponseActionExecution


class ResponseActionResource:
    @staticmethod
    def one(action: ResponseActionExecution) -> dict:
        return {
            "id": str(action.id),
            "workspace_id": str(action.workspace_id),
            "finding_fingerprint": action.finding_fingerprint,
            "kind": action.spec.kind.value,
            "status": action.status.value,
            "dry_run": action.dry_run,
            "summary": action.spec.human_summary(),
            "spec": action.spec.to_dict(),
            "inverse_spec": action.inverse_spec.to_dict(),
            "requested_by": action.requested_by,
            "requested_at": action.requested_at.isoformat() if action.requested_at else None,
            "justification": action.justification,
            "decided_by": action.decided_by,
            "decided_at": action.decided_at.isoformat() if action.decided_at else None,
            "executed_at": action.executed_at.isoformat() if action.executed_at else None,
            "execution_detail": action.execution_detail,
            "rolled_back_at": action.rolled_back_at.isoformat() if action.rolled_back_at else None,
            "error": action.error,
            "can_approve": action.status.can_approve,
            "can_reject": action.status.can_reject,
            "can_rollback": action.status.can_rollback,
        }

    @staticmethod
    def many(actions: list[ResponseActionExecution]) -> list[dict]:
        return [ResponseActionResource.one(a) for a in actions]
