"""The unified sign-off queue's application front door.

One service the queue API calls for every artifact type. It:

- **lists** the merged pending queue for a workspace (delegates to the fan-out
  query),
- **details** a single artifact (full receipts + band + target + state),
- **resolves** an artifact's workspace (so the API can enforce membership without
  the kernel ever touching a foreign context's ORM), and
- **approves / requests-changes / rejects** an artifact by delegating to that
  context's real action via ``adapter.approve`` / ``request_changes`` / ``reject``.

The RED-band anti-rubber-stamp gate lives here (uniform for the queue): a
RED-banded artifact cannot be one-click approved — an ``override_reason`` is
required BEFORE the delegated action runs. This is essential because the
delegated Send / Publish / resume use cases (newsletter, writing, workflow) do
NOT themselves enforce the sign-off risk gate — only the reports use case does,
and there the double-check is harmless/idempotent.

Every decision is audited via the injected ``SignOffAuditPort`` (the queue's
own decision trail). The production adapter writes to the shared
``EntityAuditLog`` under ``signoff.<artifact_type>`` — distinct from any
context's own field-history audit, so it complements rather than duplicates.
"""

from __future__ import annotations

import logging

from components.sign_off.application.ports.sign_off_audit_port import SignOffAuditPort
from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
    get_sign_off_registry,
)
from components.sign_off.application.services.sign_off_queue_query import (
    list_pending_sign_offs,
)
from components.sign_off.domain.errors import SignOffError
from components.sign_off.domain.services.risk_banding_policy import (
    assign_band,
    requires_override_reason,
)
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem
from components.sign_off.domain.value_objects.sign_off_target import SignOffTarget

logger = logging.getLogger(__name__)


class SignOffDetail:
    """Full detail for one artifact in the queue (state + band + target +
    the complete verification receipts)."""

    def __init__(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        review_state: ReviewState,
        risk_band: RiskBand,
        target: SignOffTarget,
        receipts: ReviewerReceipts,
        workspace_id: str | None,
    ) -> None:
        self.artifact_type = artifact_type
        self.artifact_id = artifact_id
        self.review_state = review_state
        self.risk_band = risk_band
        self.target = target
        self.receipts = receipts
        self.workspace_id = workspace_id


class SignOffQueueService:
    def __init__(
        self,
        *,
        registry: SignOffRegistry | None = None,
        audit: SignOffAuditPort | None = None,
        event_publisher=None,
    ) -> None:
        self._registry = registry or get_sign_off_registry()
        self._audit = audit
        # Optional — when wired, every decision publishes a
        # SignOffDecisionRecorded event for the feedback→eval bridge. A publish
        # failure must NEVER break a decision (see _publish_decision).
        self._event_publisher = event_publisher

    # ── Reads ────────────────────────────────────────────────────────────────

    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        return list_pending_sign_offs(workspace_id, registry=self._registry)

    def workspace_id(self, artifact_type: str, artifact_id: str) -> str | None:
        """The artifact's workspace (raises UnregisteredArtifactError for an
        unknown type; the adapter raises NotFoundError for an unknown id)."""
        return self._registry.get_adapter(artifact_type).workspace_id(artifact_id)

    def detail(self, artifact_type: str, artifact_id: str) -> SignOffDetail:
        adapter = self._registry.get_adapter(artifact_type)
        receipts = adapter.build_receipts(artifact_id)
        target = adapter.target(artifact_id)
        return SignOffDetail(
            artifact_type=artifact_type,
            artifact_id=str(artifact_id),
            review_state=adapter.get_state(artifact_id),
            risk_band=assign_band(receipts, target),
            target=target,
            receipts=receipts,
            workspace_id=adapter.workspace_id(artifact_id),
        )

    # ── Decisions ──────────────────────────────────────────────────────────────

    def approve(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str,
        override_reason: str | None = None,
    ) -> None:
        adapter = self._registry.get_adapter(artifact_type)
        band = assign_band(adapter.build_receipts(artifact_id), adapter.target(artifact_id))
        if requires_override_reason(band) and not (override_reason and override_reason.strip()):
            raise SignOffError(
                f"{artifact_type} {artifact_id} is RED-banded; approval requires an "
                "override reason (a contradicted figure or high-stakes target needs "
                "explicit justification, not a one-click approve)"
            )
        adapter.approve(str(artifact_id), actor_id=str(actor_id), override_reason=override_reason)
        self._audit_record(
            "approved",
            artifact_type,
            artifact_id,
            actor_id,
            {"band": band.value, "override_reason": override_reason},
        )
        self._publish_decision(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            decision="approved",
            actor_id=actor_id,
            risk_band=band.value,
            reason_codes=(),
            note="",
        )

    def request_changes(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str,
        codes: tuple[str, ...] = (),
        note: str = "",
    ) -> None:
        adapter = self._registry.get_adapter(artifact_type)
        adapter.request_changes(
            str(artifact_id), actor_id=str(actor_id), codes=tuple(codes), note=note
        )
        self._audit_record(
            "changes_requested",
            artifact_type,
            artifact_id,
            actor_id,
            {"codes": list(codes), "note": note},
        )
        self._publish_decision(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            decision="changes_requested",
            actor_id=actor_id,
            reason_codes=tuple(codes),
            note=note,
        )

    def reject(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        actor_id: str,
        codes: tuple[str, ...] = (),
        note: str = "",
    ) -> None:
        adapter = self._registry.get_adapter(artifact_type)
        adapter.reject(str(artifact_id), actor_id=str(actor_id), codes=tuple(codes), note=note)
        self._audit_record(
            "rejected",
            artifact_type,
            artifact_id,
            actor_id,
            {"codes": list(codes), "note": note},
        )
        self._publish_decision(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            decision="rejected",
            actor_id=actor_id,
            reason_codes=tuple(codes),
            note=note,
        )

    # ── internals ──────────────────────────────────────────────────────────────

    def _audit_record(
        self,
        event: str,
        artifact_type: str,
        artifact_id: str,
        actor_id: str,
        detail: dict,
    ) -> None:
        if self._audit is not None:
            self._audit.record(
                artifact_type=artifact_type,
                artifact_id=str(artifact_id),
                event=event,
                actor_id=str(actor_id) if actor_id is not None else None,
                detail=detail,
            )

    def _publish_decision(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        decision: str,
        actor_id: str,
        reason_codes: tuple[str, ...],
        note: str,
        risk_band: str | None = None,
    ) -> None:
        """Publish a ``SignOffDecisionRecorded`` event for the feedback→eval
        bridge.

        Guarded three ways so a publish problem can never break a decision that
        has ALREADY been delegated + audited: (1) a no-op when no publisher is
        wired, (2) the whole body wrapped in try/except that logs and never
        re-raises, and (3) the risk band resolved lazily inside the guard so a
        band recomputation error (for request_changes / reject, which don't
        precompute it) is swallowed too.
        """
        if self._event_publisher is None:
            return
        try:
            from components.shared_kernel.domain.events import SignOffDecisionRecorded

            adapter = self._registry.get_adapter(artifact_type)
            band_value = risk_band
            if band_value is None:
                band_value = assign_band(
                    adapter.build_receipts(artifact_id), adapter.target(artifact_id)
                ).value
            workspace_id = adapter.workspace_id(artifact_id)
            event = SignOffDecisionRecorded(
                artifact_type=artifact_type,
                artifact_id=str(artifact_id),
                decision=decision,
                risk_band=band_value,
                reason_codes=list(reason_codes),
                note=note or "",
                actor_id=str(actor_id) if actor_id is not None else None,
                workspace_id=str(workspace_id) if workspace_id is not None else None,
            )
            self._event_publisher.publish(event)
        except Exception:
            logger.exception(
                "sign_off_decision_publish_failed artifact_type=%s artifact_id=%s decision=%s",
                artifact_type,
                str(artifact_id),
                decision,
            )
