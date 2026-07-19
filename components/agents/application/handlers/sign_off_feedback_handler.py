"""Feedback→eval bridge handler (SEE-190).

Subscribes to ``SignOffDecisionRecorded`` (emitted by ``sign_off``'s queue
service after every approve / request-changes / reject) and records the
qualifying decisions as labeled eval examples for the content generators.

Auto-discovered at boot by ``SubscriptionRegistry.bind_all`` (it walks
``components/agents/application/handlers/*.py``), so this file is the whole
wiring — no edit to ``infrastructure/persistence/ai/apps.py`` needed.

The store is idempotent on ``(artifact_type, artifact_id, feedback_decision)``,
so an at-least-once Celery redelivery of the event is a safe no-op.
"""

from __future__ import annotations

import logging

from components.agents.application.subscription_registry_service import (
    subscribes_to,
)
from components.shared_kernel.domain.events import SignOffDecisionRecorded

logger = logging.getLogger(__name__)


@subscribes_to(SignOffDecisionRecorded)
def handle_sign_off_decision_recorded(event: SignOffDecisionRecorded) -> None:
    """Record a reviewer decision as an eval example (subject to the label
    policy in the use case).

    Lazy import of the provider keeps this module import-cheap so
    ``bind_all`` at app ready() doesn't drag the ORM into every worker boot.
    """
    from components.agents.application.providers.eval_example_provider import (
        build_record_sign_off_feedback_use_case,
    )

    use_case = build_record_sign_off_feedback_use_case()
    example_id = use_case.execute(
        artifact_type=event.artifact_type,
        artifact_id=event.artifact_id,
        decision=event.decision,
        risk_band=event.risk_band,
        reason_codes=list(event.reason_codes or []),
        note=event.note or "",
        actor_id=event.actor_id,
        workspace_id=event.workspace_id,
    )
    if example_id is None:
        # Either the label policy skipped it (rubber-stamp approve) or the
        # store deduplicated an idempotent replay — both are expected no-ops.
        logger.info(
            "sign_off_feedback_no_example artifact_type=%s artifact_id=%s decision=%s",
            event.artifact_type,
            event.artifact_id,
            event.decision,
        )
        return
    logger.info(
        "sign_off_feedback_recorded artifact_type=%s artifact_id=%s decision=%s example_id=%s",
        event.artifact_type,
        event.artifact_id,
        event.decision,
        example_id,
    )
