"""Unit tests — the rating math (ADR 0012 P5): score is DERIVED, blend is bounded.

Proves the two properties the ranking loop rests on:
1. ``derive_score`` moves monotonically with outcomes (success/reuse up, recurrence
   down) and is computed from counters only — never settable directly.
2. ``blend_rank`` lets a higher rating lift a fix of equal similarity, but keeps the
   rating a BOUNDED nudge so it can never override a much-more-relevant candidate.
"""

from __future__ import annotations

import pytest

from components.remediation.domain.services.remediation_ranking_policy import (
    RemediationRankingPolicy as P,
)

pytestmark = pytest.mark.unit


class TestDeriveScore:
    def test_baseline_for_a_fresh_vetted_entry(self):
        assert P.derive_score(reuse_count=0, success_count=0, recurrence_count=0) == P.BASELINE

    def test_success_and_reuse_raise_the_score(self):
        base = P.derive_score(reuse_count=0, success_count=0, recurrence_count=0)
        assert P.derive_score(reuse_count=1, success_count=1, recurrence_count=0) > base

    def test_recurrence_lowers_and_can_go_negative(self):
        # A fix whose finding keeps recurring MUST sink below unproven peers so
        # retrieval stops grounding on it — no non-negative clamp.
        assert P.derive_score(reuse_count=0, success_count=0, recurrence_count=3) < 0

    def test_recurrence_outweighs_a_single_success(self):
        proven = P.derive_score(reuse_count=1, success_count=1, recurrence_count=0)
        recurred = P.derive_score(reuse_count=1, success_count=1, recurrence_count=1)
        assert recurred < proven


class TestBlendRank:
    def test_higher_rating_wins_at_equal_similarity(self):
        hi = P.blend_rank(similarity=0.9, rating=10)
        lo = P.blend_rank(similarity=0.9, rating=1)
        assert hi > lo

    def test_similarity_leads_rating_cannot_override_relevance(self):
        # A far-more-similar unproven fix still beats a marginally-similar proven one.
        relevant_unproven = P.blend_rank(similarity=0.95, rating=0)
        marginal_proven = P.blend_rank(similarity=0.60, rating=1000)
        assert relevant_unproven > marginal_proven

    def test_rating_nudge_is_bounded(self):
        # The rating can shift the score by at most ±RATING_WEIGHT, no matter how big.
        base = P.blend_rank(similarity=0.5, rating=0)
        huge = P.blend_rank(similarity=0.5, rating=10_000)
        tiny = P.blend_rank(similarity=0.5, rating=-10_000)
        assert huge - base <= P.RATING_WEIGHT + 1e-9
        assert base - tiny <= P.RATING_WEIGHT + 1e-9

    def test_negative_rating_sinks_below_baseline(self):
        assert P.blend_rank(similarity=0.8, rating=-8) < P.blend_rank(similarity=0.8, rating=0)
