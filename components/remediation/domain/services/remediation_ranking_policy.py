"""RemediationRankingPolicy — derive a fix's rating from its OUTCOMES, and blend
that rating with retrieval similarity (ADR 0012 P5 — codelounge's "rated & ranked").

Two pure, deterministic functions, both framework-free (this is a domain service):

- :meth:`derive_score` turns the outcome counters (reuse / success / recurrence)
  into the integer ``score`` stored on the entry. It is the SINGLE definition of
  "how good is this fix" — computed from facts the *system* records (a later fix
  merged, a finding recurred), **never** from caller-supplied input. That is a
  security property, not just tidiness: a rating that could be set directly would
  let an attacker float a poisoned fix to the top of retrieval (D1's poisoning
  threat, in the ranking dimension). Derived-only closes that.

- :meth:`blend_rank` combines a retrieval candidate's vector SIMILARITY with its
  stored RATING into the value results are ordered by. Similarity leads (a wildly
  more relevant prior still wins); the rating is a bounded adjustment that lifts
  proven fixes above unproven ones of comparable similarity and sinks fixes whose
  finding recurred. The bound (``±RATING_WEIGHT``) is what keeps a high rating from
  ever dragging an irrelevant fix into the results.

Why the weights are shaped this way:

- A **recurrence** (the fix did NOT hold — the finding came back) is weighted more
  heavily than a reuse/success, because for a security *fix* corpus a fix that
  failed to hold is a stronger negative signal than an untested one is a positive:
  we would rather under-surface a shaky fix than teach it again.
- Every entry carries a small **baseline** (it is already vetted: sign-off approved
  + applied + resolved — D1), so a brand-new proven-once fix still ranks above an
  entry dragged negative by recurrences.
- **Recency** is emergent, not stored: every outcome re-embeds the entry (the
  capture path re-dispatches its embed), so a freshly-reinforced fix's updated
  rating reaches retrieval immediately — recent wins surface without a decaying
  timestamp term that would make the stored score drift on its own.
"""

from __future__ import annotations

import math


class RemediationRankingPolicy:
    # Score derivation weights (integer, so ``score`` stays an exact int).
    BASELINE = 1  # every vetted entry starts slightly positive (D1: it passed the gate)
    W_REUSE = 1  # grounded a later same-class fix
    W_SUCCESS = 3  # …and that fix merged/resolved (a "held" signal)
    W_RECURRENCE = 5  # the finding came back — the fix did not hold (strong negative)

    # Retrieval blend: similarity leads, rating is a bounded ±RATING_WEIGHT nudge.
    RATING_WEIGHT = 0.2
    RATING_SCALE = 4.0  # how fast the rating saturates toward the bound (tanh knee)

    @staticmethod
    def derive_score(*, reuse_count: int, success_count: int, recurrence_count: int) -> int:
        """The entry's integer rating, derived purely from its outcome counters.

        Monotonic: reuse/success raise it, recurrence lowers it. Never negative-
        clamped — a fix whose finding keeps recurring SHOULD sink below unproven
        peers so retrieval stops grounding on it.
        """
        return int(
            RemediationRankingPolicy.BASELINE
            + RemediationRankingPolicy.W_REUSE * max(0, int(reuse_count))
            + RemediationRankingPolicy.W_SUCCESS * max(0, int(success_count))
            - RemediationRankingPolicy.W_RECURRENCE * max(0, int(recurrence_count))
        )

    @staticmethod
    def blend_rank(*, similarity: float, rating: int) -> float:
        """The ordering key for a retrieval candidate: similarity + a bounded
        rating nudge in ``[-RATING_WEIGHT, +RATING_WEIGHT]``.

        ``tanh(rating / RATING_SCALE)`` maps any integer rating (which can be
        negative) into ``(-1, 1)``, so a single very-high-rated fix can never
        dominate a much-more-similar one — the rating breaks ties and lifts proven
        fixes, it does not override relevance (D2: retrieval GROUNDS, it does not
        get to pick the answer on reputation alone).
        """
        nudge = RemediationRankingPolicy.RATING_WEIGHT * math.tanh(
            float(rating) / RemediationRankingPolicy.RATING_SCALE
        )
        return float(similarity) + nudge
