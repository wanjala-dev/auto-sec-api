"""Bridge a logwatch DetectorResult into the Finding SSOT (ADR 0004 — dual-write).

Slice 1 of the logwatch → SSOT migration. When the detector cycle files a logwatch
finding on the board (the legacy path, unchanged), this ALSO emits a shared-kernel
``FindingObserved`` so the **primary log pillar** populates the Finding SSOT — the
mirror of how ``cloud_posture`` emits from ``prowler_ingest_service`` (#92).

Additive and non-breaking:
- The board Task, the ``finding_*`` workflow triggers, and specialist routing all
  still come from the legacy cycle path (``persist_finding_as_task``).
- ``FindingRaised`` emitted off this SSOT write **no-ops on the board** for logwatch
  (it is not in ``finding_raised_board_handler._SOURCE_BOARD``), so there is no
  duplicate card. The board cutover (board-from-SSOT + detector stand-down behind a
  cutover flag) is a later slice, mirroring cloud_posture #98.

Owner-persists (C2): this only *emits* the event; the ``findings`` context persists
it. No import of the findings context here. Publishing is deferred to
``transaction.on_commit`` so a rolled-back cycle never leaves an orphan SSOT finding.
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# Detector slugs whose findings dual-write into the SSOT. ``cloud_posture`` is
# deliberately NOT here — it emits ``FindingObserved`` from ``prowler_ingest_service``;
# emitting again from the cycle would double-write. Adding a slug here is how another
# detector-based pillar joins the SSOT.
LOGWATCH_SSOT_SOURCES = frozenset({"logwatch.error", "logwatch.optimization"})

# Reversible board cutover for logwatch (mirrors cloud_posture #98). When ON for a
# workspace, the cycle STOPS board-persisting logwatch results (stands down) and the
# SSOT path (FindingObserved → FindingRaised → finding_raised_board_handler) drives
# the board instead. Default OFF (per-workspace opt-in) — the flagship lane is only
# flipped once parity is observed. The board handler gates the SAME flag key.
LOGWATCH_BOARD_CUTOVER_FLAG = "feature.logwatch_board_from_findings"


def logwatch_board_cutover_active(workspace_id, result) -> bool:
    """True when the logwatch board cutover is ON for this workspace + logwatch result.

    Fail-closed: any flag-check error → False → the legacy cycle board write runs, so a
    flag-service hiccup can never drop a finding off the board. The detector cycle uses
    this to decide whether to board-persist (legacy) or defer to the SSOT path.
    """
    slug = (getattr(result, "detector_slug", "") or "").strip()
    if slug not in LOGWATCH_SSOT_SOURCES:
        return False
    try:
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        return bool(
            get_feature_flags_provider().is_feature_enabled(LOGWATCH_BOARD_CUTOVER_FLAG, workspace_id=workspace_id)
        )
    except Exception:
        logger.exception("logwatch_board_cutover_flag_check_failed workspace_id=%s", workspace_id)
        return False


def emit_finding_observed_for_detector_result(workspace_id, result, *, publisher=None) -> None:
    """Emit ``FindingObserved`` for a logwatch DetectorResult (best-effort, on commit).

    No-op for any non-logwatch detector (gate on ``detector_slug``). Never raises — an
    SSOT emission hiccup must not break the detector cycle; the board write already
    happened and is the source of truth until the board cutover slice.
    """
    slug = (getattr(result, "detector_slug", "") or "").strip()
    if slug not in LOGWATCH_SSOT_SOURCES:
        return
    try:
        event = _build_finding_observed(workspace_id, result)
    except Exception:
        logger.exception("logwatch_finding_observed_build_failed workspace_id=%s slug=%s", workspace_id, slug)
        return
    _publish_on_commit(event, publisher)


def _build_finding_observed(workspace_id, result):
    # ``_derive_severity`` is the canonical impact_score → band mapper; reuse it so the
    # SSOT finding's severity is identical to the board Task's (parity), never a second
    # threshold table.
    from components.agents.application.handlers.specialist_persistence_service import (
        _derive_severity,
    )
    from components.shared_kernel.domain.events import FindingObserved
    from components.shared_kernel.domain.security import AssetUrn

    payload = result.payload or {}
    # ``lookup_key`` is the one name a detector payload carries its identity
    # under (ADR 0032 §1.3.3 / D6). The ``or payload["fingerprint"]`` fallback
    # that used to sit here kept a second name alive for the same value; the
    # log-watch contracts no longer emit it.
    fingerprint = str(payload.get("lookup_key") or "").strip()
    if not fingerprint:
        raise ValueError("logwatch finding carries no lookup_key")

    service = (str(payload.get("service") or "").strip()) or "unknown"
    impact_score = int((result.metadata or {}).get("impact_score", 0))
    severity = _derive_severity(impact_score)

    # A log/service asset has no ARN. Namespace it as ``urn:log:<workspace>/<service>``
    # so it is a stable, cross-pillar-correlatable identity — a cloud finding on the
    # same host can later carry the matching URN and the two correlate by value (C4).
    ws = workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
    asset_urn = AssetUrn.canonical("log", f"{ws}/{service}").value

    return FindingObserved(
        workspace_id=ws,
        source=result.detector_slug,
        fingerprint=fingerprint,
        asset_urn=asset_urn,
        severity=severity,
        title=result.title,
        description=(result.summary or "")[:2000],
        remediation="",  # logwatch leaves remediation to the triage/optimization agent
        attributes={
            "service": service,
            "signal": str(payload.get("signal") or ""),
            "action_type": result.action_type,
            "detector_slug": result.detector_slug,
            "blast_radius": (result.context or {}).get("blast_radius") or payload.get("blast_radius") or {},
            # Everything the board-cutover path needs to rebuild the EXACT legacy card
            # (identical source_type / agent_type / payload / context / lookup_key → a
            # board-invisible cutover with full triage evidence preserved). Consumed by
            # ``finding_raised_board_handler._build_logwatch_card``.
            "agent_type": result.agent_type or "ai_teammate",
            "impact_score": impact_score,
            "board_payload": dict(payload),
            "board_context": dict(result.context or {}),
        },
    )


def _publish_on_commit(event, publisher) -> None:
    from django.db import transaction

    def _emit(pub=publisher):
        if pub is None:
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            pub = CeleryEventPublisher()
        pub.publish(event)

    transaction.on_commit(_emit)
