"""Risk-banding policy — the pure decision that drives review friction.

Two steps:

1. Content band from the verification receipts:
     - a figure the source data CONTRADICTS            -> RED
     - any unverifiable figure / ungrounded claim / voice flag -> AMBER
     - clean                                            -> GREEN
2. Escalate one level when the target raises the stakes (external delivery or
   an explicitly high-stakes artifact such as a funder submission).

The function is intentionally pure (receipts + target -> band) so the full
decision table is exhaustively unit-testable with no DB or framework. This is
the load-bearing, R&D-eligible part of the kernel.
"""

from __future__ import annotations

from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.risk_band import RiskBand, escalate
from components.sign_off.domain.value_objects.sign_off_target import SignOffTarget


def content_band(receipts: ReviewerReceipts) -> RiskBand:
    """The band implied by the verification signal alone, ignoring audience."""
    if receipts.has_contradictions:
        return RiskBand.RED
    if receipts.has_flags:
        return RiskBand.AMBER
    return RiskBand.GREEN


def assign_band(receipts: ReviewerReceipts, target: SignOffTarget) -> RiskBand:
    """Final risk band = content band, escalated one level by stakes/audience."""
    band = content_band(receipts)
    if target.escalates:
        band = escalate(band, 1)
    return band


def requires_override_reason(band: RiskBand) -> bool:
    """Red artifacts can't be one-click approved — they need an explicit reason
    (the 'forced justification' the meaningful-oversight research prescribes)."""
    return band == RiskBand.RED


def approval_unlocks_state() -> ReviewState:
    """The state a successful sign-off transitions an artifact into."""
    return ReviewState.APPROVED
