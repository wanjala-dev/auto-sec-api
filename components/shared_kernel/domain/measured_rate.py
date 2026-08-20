"""The ONE statistic for measured trust (ADR 0032 D3 + D4).

Every rate this product displays that drives a decision goes through here.
Not a mean, not a Wald interval, not a bare percentage — a one-sided 95%
Wilson bound carried together with the trial count and an explicit
three-state verdict.

WHY THIS MODULE EXISTS AT ALL. The mechanism was already written and
already correct, in ``components/code_security/domain/fix_confidence.py``:
Wilson bound, minimum-trials floor, evidence expiry, three tiers, and
"absence is a verdict". It was written for ONE caller (per-SAST-rule fix
confidence) and the whole of it except the SAST rule-corpus loader is
domain-neutral. ADR 0032 D3 needs the same statistic for agent/model
measurement, so the choice was "generalise" or "write a second one".
A second one is the defect ``dry-reuse.md`` §4 forbids — two confidence
numbers for the same fact, drifting apart the first time one gets a fix
the other misses. So the statistic and the tier ladder live HERE, in the
shared kernel, and ``fix_confidence`` consumes them. There is exactly one
Wilson implementation in this codebase and this is it.

TWO VOCABULARIES, DELIBERATELY.

* **Tiers** (``proven`` / ``measured_weak`` / ``unproven``) answer *"may
  this be trusted to act unattended?"*. Three, not a boolean, because
  "never measured" and "measured and found wanting" are different facts
  leading to different work.
* **States** (``no_data`` / ``too_few`` / ``measured``) answer *"what may
  a panel render?"* — ADR 0032 D4. They exist because a panel that reads
  green when nothing ran is the same defect as PR #415's empty report
  reading clean. ``no_data`` is NEVER green; it is the absence of a
  measurement, not a good measurement.

They are related but not the same axis: a tier is a judgement against a
threshold, a state is a statement about how much evidence exists. A rate
with no threshold (a failure rate on a dashboard) has a state and no tier.

WHY BOTH BOUNDS. A success rate is read optimistically, so it is reported
by its LOWER bound (2/2 → 0.43, not 1.0). A failure rate is read
optimistically in the other direction — "0 failures in 12 runs" reads as
"never fails" — so it is reported by its UPPER bound, which at 0/12 is
0.25, not 0.0 (Hanley & Lippman-Hand's rule of three, ≈3/n; the Wilson
upper bound agrees to within a couple of points and is used because it
also holds when the numerator is non-zero).

Framework-free: stdlib only. No Django, no ORM, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: One-sided 95% normal quantile, for the Wilson bounds.
Z_ONE_SIDED_95 = 1.6448536269514722

#: Tiers — the trust ladder. Deliberately three, not a boolean: "never
#: measured" and "measured and found wanting" lead to different work
#: (go measure it / go fix the thing).
TIER_PROVEN = "proven"
TIER_MEASURED_WEAK = "measured_weak"
TIER_UNPROVEN = "unproven"

#: Display states (ADR 0032 D4). ``no_data`` must never render as a good
#: outcome — it is the absence of a measurement.
STATE_NO_DATA = "no_data"
STATE_TOO_FEW = "too_few"
STATE_MEASURED = "measured"


def wilson_lower_bound(passes: int, trials: int, *, z: float = Z_ONE_SIDED_95) -> float:
    """One-sided 95% Wilson lower bound on the success rate.

    Wilson rather than the normal approximation because at our n the normal
    interval is not merely wide but wrong — for a clean run it collapses to
    [1.0, 1.0], reporting certainty from two observations. Wilson stays inside
    [0, 1] and keeps a perfect small sample honest: 2/2 → 0.43, 20/20 → 0.88.
    """
    if trials <= 0:
        return 0.0
    passes = max(0, min(passes, trials))
    p = passes / trials
    denominator = 1 + (z**2) / trials
    centre = (p + (z**2) / (2 * trials)) / denominator
    margin = (z / denominator) * math.sqrt((p * (1 - p) / trials) + (z**2) / (4 * trials**2))
    return max(0.0, centre - margin)


def wilson_upper_bound(passes: int, trials: int, *, z: float = Z_ONE_SIDED_95) -> float:
    """One-sided 95% Wilson UPPER bound on the rate.

    The mirror of :func:`wilson_lower_bound`, and the honest way to report a
    rate whose optimistic reading is *low* — a failure rate. 0 failures in 12
    runs has an upper bound of ~0.22, not 0.0: the run of clean results is
    consistent with a system that fails roughly one time in five.
    """
    if trials <= 0:
        return 1.0
    passes = max(0, min(passes, trials))
    p = passes / trials
    denominator = 1 + (z**2) / trials
    centre = (p + (z**2) / (2 * trials)) / denominator
    margin = (z / denominator) * math.sqrt((p * (1 - p) / trials) + (z**2) / (4 * trials**2))
    return min(1.0, centre + margin)


def rule_of_three_upper_bound(trials: int) -> float:
    """95% upper bound on an event rate after ZERO observed events: ≈ 3/n.

    Hanley & Lippman-Hand (1983). Kept as its own named function because it
    is the sentence an operator needs when a panel shows a clean streak:
    "0 failures in 12 runs is consistent with a 25% failure rate." Callers
    that also handle non-zero numerators should use
    :func:`wilson_upper_bound`, which agrees closely here and generalises.
    """
    if trials <= 0:
        return 1.0
    return min(1.0, 3.0 / trials)


@dataclass(frozen=True)
class MeasuredRate:
    """A rate you may safely put on a screen: bound, n, and a state.

    ``point`` is retained for completeness but is NEVER the headline — the
    whole reason this type exists is that "3 of 4 = 75%" is the failure
    mode. Render ``summary``, or render ``bound`` WITH ``trials``.
    """

    observed: int
    trials: int
    state: str
    point: float | None
    lower_bound: float
    upper_bound: float
    min_trials: int
    summary: str

    @property
    def is_measured(self) -> bool:
        return self.state == STATE_MEASURED

    def as_dict(self) -> dict:
        """The wire shape. ``state`` is part of the contract, not a UI choice."""
        return {
            "state": self.state,
            "observed": self.observed,
            "trials": self.trials,
            "point": round(self.point, 4) if self.point is not None else None,
            "lower_bound": round(self.lower_bound, 4),
            "upper_bound": round(self.upper_bound, 4),
            "min_trials": self.min_trials,
            "summary": self.summary,
        }


def measure_rate(
    observed: int,
    trials: int,
    *,
    min_trials: int,
    noun: str = "observations",
    event: str = "",
) -> MeasuredRate:
    """Turn a raw fraction into a three-state, bounded, n-carrying rate.

    ``noun`` names the denominator ("runs", "graded answers") and ``event``
    names the numerator ("failed", "passed"); both only shape ``summary``,
    which is written so a panel can render it verbatim rather than inventing
    its own wording per surface.

    Never raises and never returns ``None``: zero trials is ``no_data``, which
    is a verdict, not a missing value.
    """
    trials = max(0, int(trials))
    observed = max(0, min(int(observed), trials))
    lower = wilson_lower_bound(observed, trials)
    upper = wilson_upper_bound(observed, trials)
    point = (observed / trials) if trials else None
    event_label = f"{event} " if event else ""

    if trials == 0:
        return MeasuredRate(
            observed=0,
            trials=0,
            state=STATE_NO_DATA,
            point=None,
            lower_bound=lower,
            upper_bound=upper,
            min_trials=min_trials,
            summary=f"Not measured — 0 {noun} in this window",
        )

    if trials < min_trials:
        return MeasuredRate(
            observed=observed,
            trials=trials,
            state=STATE_TOO_FEW,
            point=point,
            lower_bound=lower,
            upper_bound=upper,
            min_trials=min_trials,
            summary=(
                f"{observed}/{trials} {event_label}— {min_trials} {noun} are the floor; "
                f"too few to distinguish a good result from a lucky one "
                f"(95% bounds {lower:.0%}–{upper:.0%})"
            ),
        )

    return MeasuredRate(
        observed=observed,
        trials=trials,
        state=STATE_MEASURED,
        point=point,
        lower_bound=lower,
        upper_bound=upper,
        min_trials=min_trials,
        summary=f"{observed}/{trials} {event_label}— 95% bounds {lower:.0%}–{upper:.0%}",
    )
