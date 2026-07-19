"""Build a normalized ``SignOffItem`` from an adapter + artifact identity.

Each adapter's ``list_pending`` uses this so every queue row is computed the
SAME way — one build_receipts call feeds both the risk band and the summary
counts, and the audience/state come straight off the port. Keeping this in the
kernel (not duplicated per adapter) means the risk-banding rule is applied
identically to every artifact type.
"""

from __future__ import annotations

from datetime import datetime

from components.sign_off.application.ports.sign_off_port import SignOffPort
from components.sign_off.domain.services.risk_banding_policy import assign_band
from components.sign_off.domain.value_objects.sign_off_item import (
    ReceiptsSummary,
    SignOffItem,
)


def build_sign_off_item(
    adapter: SignOffPort,
    artifact_id: str,
    *,
    title: str,
    workspace_id: str | None,
    created_at: datetime | None,
) -> SignOffItem:
    """Project one artifact into a queue row.

    ``build_receipts`` is called once and reused for both the risk band and the
    summary counts so the (potentially expensive) verification signal runs a
    single time per row.
    """
    receipts = adapter.build_receipts(artifact_id)
    target = adapter.target(artifact_id)
    return SignOffItem(
        artifact_type=adapter.artifact_type(),
        artifact_id=str(artifact_id),
        title=title,
        review_state=adapter.get_state(artifact_id),
        risk_band=assign_band(receipts, target),
        audience=target.audience.value,
        receipts_summary=ReceiptsSummary.from_receipts(receipts),
        workspace_id=str(workspace_id) if workspace_id else None,
        created_at=created_at,
    )
