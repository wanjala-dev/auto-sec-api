"""In-memory fakes for kernel unit tests (one fake per port, per the testing skill)."""

from __future__ import annotations

from components.sign_off.application.ports.sign_off_audit_port import SignOffAuditPort
from components.sign_off.application.ports.sign_off_port import SignOffPort
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget


class FakeSignOffAdapter(SignOffPort):
    """A standalone artifact whose state, receipts, and target are set in-test."""

    def __init__(
        self,
        artifact_type: str,
        *,
        state: ReviewState = ReviewState.PENDING,
        receipts: ReviewerReceipts | None = None,
        target: SignOffTarget | None = None,
        workspace_id: str | None = "ws-1",
        pending: list[SignOffItem] | None = None,
        list_pending_error: Exception | None = None,
    ) -> None:
        self._artifact_type = artifact_type
        self._state: dict[str, ReviewState] = {}
        self._default_state = state
        self._receipts = receipts or ReviewerReceipts()
        self._target = target or SignOffTarget(Audience.INTERNAL_TEAM)
        self._workspace_id = workspace_id
        self._pending = pending if pending is not None else []
        self._list_pending_error = list_pending_error
        # Records of the delegated decisions the queue service drove.
        self.approved: list[dict] = []
        self.changes_requested: list[dict] = []
        self.rejected: list[dict] = []

    def artifact_type(self) -> str:
        return self._artifact_type

    def get_state(self, artifact_id: str) -> ReviewState:
        return self._state.get(artifact_id, self._default_state)

    def set_state(self, artifact_id: str, state: ReviewState) -> None:
        self._state[artifact_id] = state

    def build_receipts(self, artifact_id: str) -> ReviewerReceipts:
        return self._receipts

    def target(self, artifact_id: str) -> SignOffTarget:
        return self._target

    def workspace_id(self, artifact_id: str) -> str | None:
        return self._workspace_id

    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        if self._list_pending_error is not None:
            raise self._list_pending_error
        return list(self._pending)

    def approve(self, artifact_id, *, actor_id, override_reason=None) -> None:
        self.approved.append(
            {"artifact_id": artifact_id, "actor_id": actor_id, "override_reason": override_reason}
        )
        self.set_state(artifact_id, ReviewState.APPROVED)

    def request_changes(self, artifact_id, *, actor_id, codes=(), note="") -> None:
        self.changes_requested.append(
            {"artifact_id": artifact_id, "actor_id": actor_id, "codes": tuple(codes), "note": note}
        )

    def reject(self, artifact_id, *, actor_id, codes=(), note="") -> None:
        self.rejected.append(
            {"artifact_id": artifact_id, "actor_id": actor_id, "codes": tuple(codes), "note": note}
        )
        self.set_state(artifact_id, ReviewState.REJECTED)


class FakeAudit(SignOffAuditPort):
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, artifact_type, artifact_id, event, actor_id, detail=None) -> None:
        self.entries.append(
            {
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "event": event,
                "actor_id": actor_id,
                "detail": detail,
            }
        )
