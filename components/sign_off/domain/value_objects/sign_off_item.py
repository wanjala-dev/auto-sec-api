"""SignOffItem — one normalized row in the unified sign-off queue.

Every registered adapter (report, newsletter, writing draft, workflow email)
projects its own pending artifacts into this shape so the queue API can list
them uniformly — same review state, same risk band, same lightweight receipts
summary — regardless of which context owns the underlying row.

The summary carries only the *counts* the queue UI needs to render a risk chip
(N unverified figures, N ungrounded claims, N voice flags, clean?). The full
``ReviewerReceipts`` packet is fetched lazily on the detail endpoint — no need
to serialize every claim for a list view.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.risk_band import RiskBand


@dataclass(frozen=True)
class ReceiptsSummary:
    """Counts distilled from a full ``ReviewerReceipts`` packet for a list row."""

    unverified_figures: int = 0
    ungrounded_claims: int = 0
    voice_flags: int = 0
    is_clean: bool = True

    @classmethod
    def from_receipts(cls, receipts: ReviewerReceipts) -> "ReceiptsSummary":
        # "unverified" = every figure the source data did not confirm, whether
        # it was contradicted (red) or simply unverifiable (amber). Both are
        # figures the reviewer must eyeball.
        unverified = sum(1 for fc in receipts.figure_checks if not fc.verified)
        return cls(
            unverified_figures=unverified,
            ungrounded_claims=len(receipts.ungrounded_claims),
            voice_flags=len(receipts.voice_flags),
            is_clean=receipts.is_clean,
        )


@dataclass(frozen=True)
class SignOffItem:
    """A normalized pending-sign-off row for the unified queue."""

    artifact_type: str
    artifact_id: str
    title: str
    review_state: ReviewState
    risk_band: RiskBand
    audience: str
    receipts_summary: ReceiptsSummary
    workspace_id: str | None = None
    created_at: datetime | None = None
