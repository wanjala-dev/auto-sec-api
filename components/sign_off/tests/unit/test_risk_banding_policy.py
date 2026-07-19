"""Exhaustive decision-table tests for the risk-banding policy — the core,
R&D-eligible part of the kernel. Pure functions, no DB/framework.
"""

from __future__ import annotations

import pytest

from components.sign_off.domain.services.risk_banding_policy import (
    assign_band,
    content_band,
    requires_override_reason,
)
from components.sign_off.domain.value_objects.reviewer_receipts import (
    ClaimProvenance,
    FigureCheck,
    ReviewerReceipts,
    VoiceFlag,
)
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget

pytestmark = pytest.mark.unit


# --- receipt fixtures -------------------------------------------------------

CLEAN = ReviewerReceipts(
    figure_checks=(FigureCheck("$32k raised", "32000", "32000", verified=True, source_ref="ledger"),),
    claim_provenance=(ClaimProvenance("we ran a literacy camp", "project:42", grounded=True),),
)
UNVERIFIABLE_FIGURE = ReviewerReceipts(
    figure_checks=(FigureCheck("$40k raised", "40000", source_value=None, verified=False),),
)
UNGROUNDED_CLAIM = ReviewerReceipts(
    claim_provenance=(ClaimProvenance("we are the largest charity in Kenya", None, grounded=False),),
)
VOICE_ONLY = ReviewerReceipts(voice_flags=(VoiceFlag("desperately need", "negative framing"),))
CONTRADICTED = ReviewerReceipts(
    figure_checks=(FigureCheck("$40k raised", "40000", source_value="32000", verified=False, source_ref="ledger"),),
)

SELF = SignOffTarget(Audience.INTERNAL_SELF)
TEAM = SignOffTarget(Audience.INTERNAL_TEAM)
EXTERNAL = SignOffTarget(Audience.EXTERNAL)
HIGH_STAKES = SignOffTarget(Audience.INTERNAL_TEAM, high_stakes=True)


# --- content band (audience-independent) ------------------------------------

def test_clean_is_green():
    assert content_band(CLEAN) == RiskBand.GREEN


@pytest.mark.parametrize("receipts", [UNVERIFIABLE_FIGURE, UNGROUNDED_CLAIM, VOICE_ONLY])
def test_any_flag_is_amber(receipts):
    assert content_band(receipts) == RiskBand.AMBER


def test_contradiction_is_red():
    assert content_band(CONTRADICTED) == RiskBand.RED


def test_contradiction_dominates_other_flags():
    mixed = ReviewerReceipts(
        figure_checks=(
            FigureCheck("$40k", "40000", "32000", verified=False),  # contradicted
            FigureCheck("$5k", "5000", None, verified=False),  # unverifiable
        ),
        voice_flags=(VoiceFlag("x", "jargon"),),
    )
    assert content_band(mixed) == RiskBand.RED


# --- full policy: content band + stakes/audience escalation -----------------

@pytest.mark.parametrize(
    "receipts,target,expected",
    [
        # clean content, escalation only from target
        (CLEAN, SELF, RiskBand.GREEN),
        (CLEAN, TEAM, RiskBand.GREEN),
        (CLEAN, EXTERNAL, RiskBand.AMBER),  # external bumps green -> amber
        (CLEAN, HIGH_STAKES, RiskBand.AMBER),  # high-stakes bumps green -> amber
        # amber content
        (UNVERIFIABLE_FIGURE, SELF, RiskBand.AMBER),
        (UNVERIFIABLE_FIGURE, EXTERNAL, RiskBand.RED),  # external bumps amber -> red
        (VOICE_ONLY, HIGH_STAKES, RiskBand.RED),  # high-stakes bumps amber -> red
        # red content stays red regardless, escalation can't exceed red
        (CONTRADICTED, SELF, RiskBand.RED),
        (CONTRADICTED, EXTERNAL, RiskBand.RED),
    ],
)
def test_assign_band_decision_table(receipts, target, expected):
    assert assign_band(receipts, target) == expected


def test_only_red_requires_override_reason():
    assert requires_override_reason(RiskBand.RED) is True
    assert requires_override_reason(RiskBand.AMBER) is False
    assert requires_override_reason(RiskBand.GREEN) is False
