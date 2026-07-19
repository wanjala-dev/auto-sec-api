"""Orchestrates the sign-off lifecycle for any registered artifact.

Reads the verification receipts, computes the risk band, validates the
review-state transition, persists it via the adapter, and records an immutable
audit entry. The risk band governs *friction*, never *bypass*:

- A RED artifact cannot be one-click approved — ``approve`` requires an
  ``override_reason`` (the forced-justification anti-rubber-stamp control).
- Every decision is audited with the band at decision time + any override.
"""

from __future__ import annotations

from components.sign_off.application.ports.sign_off_audit_port import SignOffAuditPort
from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
    get_sign_off_registry,
)
from components.sign_off.domain.errors import SignOffError
from components.sign_off.domain.services.risk_banding_policy import (
    assign_band,
    requires_override_reason,
)
from components.sign_off.domain.value_objects.review_state import ReviewState, assert_transition
from components.sign_off.domain.value_objects.risk_band import RiskBand


class SignOffService:
    def __init__(
        self,
        *,
        registry: SignOffRegistry | None = None,
        audit: SignOffAuditPort | None = None,
    ) -> None:
        self._registry = registry or get_sign_off_registry()
        self._audit = audit

    def assess(self, artifact_type: str, artifact_id: str) -> RiskBand:
        """Compute the current risk band for an artifact (drives queue friction)."""
        adapter = self._registry.get_adapter(artifact_type)
        return assign_band(adapter.build_receipts(artifact_id), adapter.target(artifact_id))

    def submit_for_review(
        self, artifact_type: str, artifact_id: str, *, actor_id: str | None = None
    ) -> ReviewState:
        return self._transition(
            artifact_type, artifact_id, ReviewState.PENDING, actor_id=actor_id, event="submitted"
        )

    def approve(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str | None = None,
        override_reason: str | None = None,
    ) -> ReviewState:
        band = self.assess(artifact_type, artifact_id)
        if requires_override_reason(band) and not (override_reason and override_reason.strip()):
            raise SignOffError(
                f"{artifact_type} {artifact_id} is RED-banded; approval requires an "
                "override reason (a contradicted figure or high-stakes target needs "
                "explicit justification, not a one-click approve)"
            )
        return self._transition(
            artifact_type,
            artifact_id,
            ReviewState.APPROVED,
            actor_id=actor_id,
            event="approved",
            detail={"band": band.value, "override_reason": override_reason},
        )

    def request_changes(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str | None = None,
        codes: tuple[str, ...] = (),
        note: str = "",
    ) -> ReviewState:
        return self._transition(
            artifact_type,
            artifact_id,
            ReviewState.CHANGES_REQUESTED,
            actor_id=actor_id,
            event="changes_requested",
            detail={"codes": list(codes), "note": note},
        )

    def reject(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str | None = None,
        codes: tuple[str, ...] = (),
        note: str = "",
    ) -> ReviewState:
        return self._transition(
            artifact_type,
            artifact_id,
            ReviewState.REJECTED,
            actor_id=actor_id,
            event="rejected",
            detail={"codes": list(codes), "note": note},
        )

    def _transition(
        self,
        artifact_type: str,
        artifact_id: str,
        target_state: ReviewState,
        *,
        actor_id: str | None,
        event: str,
        detail: dict | None = None,
    ) -> ReviewState:
        adapter = self._registry.get_adapter(artifact_type)
        current = adapter.get_state(artifact_id)
        assert_transition(current, target_state)
        adapter.set_state(artifact_id, target_state)
        if self._audit is not None:
            self._audit.record(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                event=event,
                actor_id=actor_id,
                detail=detail,
            )
        return target_state
