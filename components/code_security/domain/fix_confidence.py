"""Per-rule fix confidence — is the advisor MEASURABLY good at this rule? (#117 step 3)

THE GAP THIS CLOSES. The verifier already labels each suggestion ``verified`` or
``unverified`` by grounding it in that finding's evidence. That is a per-FINDING
check, and it cannot see the failure that started this whole task: PR #866's
patch was grounded, in scope, syntactically valid — and semantically wrong,
because Postgres cannot parameterise an identifier. Grounding had nothing to say
about it. "We have never measured this rule" would have.

So this module answers a different question from the verifier:

    verifier      → does THIS patch reference THIS finding's evidence?
    this module   → historically, does the advisor get THIS RULE right?

Both are labels. Neither is a gate in front of the artifact — see below.

IT LABELS, IT DOES NOT BLOCK (standing product rule, Henry 2026-08-09). A
finding in a connected repository always carries its draft PR; a confidence
problem downgrades the LABEL and never withholds the artifact, because a draft
PR cannot merge itself and a bare "NEEDS HUMAN" chip with nothing behind it is
the noise this product exists to remove. The rule names this task by name:
fix-quality work is "complementary, not a gate that blanks output". What
:func:`confidence_for` gates is the tier ABOVE the draft PR — unattended
auto-fix — which is exactly the tier we cannot currently justify.

WHY EVIDENCE AND NOT A FLAG. The obvious implementation is ``autofix: true`` per
rule in ``classes.yaml``. That is how we got a 1-in-5 baseline: a hand-authored
claim about quality, with nothing behind it, that nobody re-checks. Everything
here is derived from COUNTS produced by the eval harness, and three bindings
make stale or borrowed evidence inert rather than quietly wrong:

* ``model`` — a measurement is about ONE model. The vendor ships a new version
  and yesterday's numbers describe a system that no longer exists. Checked at
  RESOLVE time: evidence measured on a different model resolves ``UNPROVEN``.
* ``measured_at`` — evidence expires. Not because the code rots, but because
  the model underneath it moves without a commit on our side. Also checked at
  resolve time.
* ``corpus_digest`` — evidence is bound to the fixture corpus it was measured
  on; edit the corpus and every prior measurement is void. This one is
  enforced by the FITNESS TEST beside the corpus (test_fixture_integrity),
  not here: the fixtures live in the agents context, and this domain module
  computing their digest would cross that boundary. CI fails loudly the
  moment committed evidence describes a corpus that no longer exists.

A mismatch resolves ``UNPROVEN``, which is also what an unknown rule returns.
Fail-closed: the absence of evidence is never read as evidence of adequacy.

WHY A CONFIDENCE BOUND AND NOT A RATIO. "2 out of 2" is not a 100% success
rate; at n=2 it is barely distinguishable from a coin. We score the one-sided
lower confidence bound (Wilson), so the trial COUNT is part of the verdict
rather than a footnote — a perfect 2/2 scores 0.43 and is refused, while 20/20
scores 0.88 and is not. This is Tom's own advice for trusting non-deterministic
output (run it enough times to reach significance, then read the confidence),
applied to the thing we would otherwise be tempted to eyeball.

Framework-free: no Django, no ORM, stdlib + yaml. Mirrors the loading contract
of :mod:`remediation_guidance` — loud on a malformed corpus, graceful on a miss.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: Public so the eval harness command can WRITE evidence to the one true
#: location instead of hardcoding a second copy of this path.
EVIDENCE_FILE = Path(__file__).resolve().parents[1] / "rules" / "remediation" / "fix_confidence.yaml"

#: One-sided 95% normal quantile, for the Wilson lower bound.
_Z = 1.6448536269514722

#: A rule must clear this lower bound before unattended auto-fix is considered.
#: 0.85 is not a rounded-off guess: with a clean run it is reached at ~20 trials
#: and not before, which is the point — the threshold encodes "measured enough
#: times to mean something", not "looked good once".
AUTOFIX_LOWER_BOUND = 0.85

#: Floor on trials regardless of the bound. The Wilson bound already punishes
#: small n, but a hard floor makes the refusal message say the true reason
#: ("2 trials") instead of an abstract score an operator cannot act on.
AUTOFIX_MIN_TRIALS = 10

#: Evidence older than this is treated as absent. The model changes underneath a
#: measurement without any commit on our side, so a number with no expiry slowly
#: becomes a claim about a system that no longer exists.
EVIDENCE_MAX_AGE_DAYS = 90

#: Tiers. Deliberately three, not a boolean: "never measured" and "measured and
#: found wanting" are different facts about a rule and lead to different work
#: (go measure it / go fix the guidance).
TIER_PROVEN = "proven"
TIER_MEASURED_WEAK = "measured_weak"
TIER_UNPROVEN = "unproven"


class FixConfidenceError(RuntimeError):
    """The evidence corpus is malformed — fail loud, never guess."""


@dataclass(frozen=True)
class FixEvidence:
    """Measured outcomes for one rule, produced by the eval harness."""

    rule_id: str
    trials: int
    passes: int
    corpus_digest: str
    model: str
    measured_at: date
    note: str = ""


@dataclass(frozen=True)
class FixConfidence:
    """The verdict for one rule: a tier, the numbers behind it, and the reason."""

    rule_id: str
    tier: str
    reason: str
    trials: int
    passes: int
    lower_bound: float

    @property
    def autofix_permitted(self) -> bool:
        """Unattended auto-fix. NOT whether a draft PR may open — that always may."""
        return self.tier == TIER_PROVEN

    def as_label(self) -> dict:
        """The shape that rides a finding's payload for the PR body and the HUD."""
        return {
            "tier": self.tier,
            "reason": self.reason,
            "trials": self.trials,
            "passes": self.passes,
            "lower_bound": round(self.lower_bound, 3),
        }


def wilson_lower_bound(passes: int, trials: int) -> float:
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
    denominator = 1 + (_Z**2) / trials
    centre = (p + (_Z**2) / (2 * trials)) / denominator
    margin = (_Z / denominator) * math.sqrt((p * (1 - p) / trials) + (_Z**2) / (4 * trials**2))
    return max(0.0, centre - margin)


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, FixEvidence], str, str]:
    """Return ``(evidence_by_rule, corpus_digest, model)`` — cached.

    A MISSING file is legitimate and means "nothing has been measured": every
    rule resolves to ``UNPROVEN``, which is the correct reading. A file that
    EXISTS but is malformed raises — a corrupt evidence corpus silently read as
    "no evidence" would look identical to the honest empty case.
    """
    if not EVIDENCE_FILE.is_file():
        logger.info("fix_confidence no evidence corpus at %s — every rule is unproven", EVIDENCE_FILE)
        return {}, "", ""

    doc = yaml.safe_load(EVIDENCE_FILE.read_text()) or {}
    corpus_digest = str(doc.get("corpus_digest") or "").strip()
    model = str(doc.get("model") or "").strip()
    raw = doc.get("rules") or {}
    if not isinstance(raw, dict):
        raise FixConfidenceError("fix_confidence.yaml: 'rules' must be a mapping of rule_id → measurement")

    evidence: dict[str, FixEvidence] = {}
    for rule_id, body in raw.items():
        body = body or {}
        try:
            trials = int(body["trials"])
            passes = int(body["passes"])
            measured_at = body["measured_at"]
        except (KeyError, TypeError, ValueError) as exc:
            raise FixConfidenceError(
                f"fix_confidence.yaml: rule {rule_id!r} needs trials, passes, measured_at"
            ) from exc
        if isinstance(measured_at, str):
            measured_at = date.fromisoformat(measured_at)
        if not isinstance(measured_at, date):
            raise FixConfidenceError(f"fix_confidence.yaml: rule {rule_id!r} measured_at must be a date")
        if passes > trials or trials < 0 or passes < 0:
            raise FixConfidenceError(f"fix_confidence.yaml: rule {rule_id!r} has passes={passes} trials={trials}")
        evidence[str(rule_id)] = FixEvidence(
            rule_id=str(rule_id),
            trials=trials,
            passes=passes,
            corpus_digest=str(body.get("corpus_digest") or corpus_digest),
            model=str(body.get("model") or model),
            measured_at=measured_at,
            note=str(body.get("note") or ""),
        )
    return evidence, corpus_digest, model


def measured_rules() -> dict[str, FixEvidence]:
    """Every rule carrying evidence (for the fitness tests + diagnostics)."""
    return dict(_load()[0])


def corpus_digest() -> str:
    """The fixture-corpus digest the committed evidence was measured against."""
    return _load()[1]


def confidence_for(rule_id: str, *, model: str, today: date | None = None) -> FixConfidence:
    """Resolve a rule's fix confidence. NEVER returns ``None`` — absence is a verdict.

    ``model`` is required and unforgiving: evidence gathered on a different
    model does not transfer, and a caller that cannot say which model is running
    cannot be told a rule is proven. Passing ``""`` therefore yields
    ``UNPROVEN`` rather than a bound computed from numbers about some other
    system.
    """
    today = today or date.today()
    evidence, _, _ = _load()
    key = str(rule_id or "").strip()

    def unproven(reason: str, ev: FixEvidence | None = None) -> FixConfidence:
        return FixConfidence(
            rule_id=key,
            tier=TIER_UNPROVEN,
            reason=reason,
            trials=ev.trials if ev else 0,
            passes=ev.passes if ev else 0,
            lower_bound=0.0,
        )

    if not key:
        return unproven("no rule id supplied")

    ev = evidence.get(key)
    if ev is None:
        return unproven("this rule has never been measured against the fix corpus")

    if not model:
        return unproven("the running model was not declared, so measurements cannot be attributed to it", ev)
    if ev.model and ev.model != model:
        return unproven(f"measured on {ev.model}, running {model} — measurements do not transfer between models", ev)

    age = (today - ev.measured_at).days
    if age > EVIDENCE_MAX_AGE_DAYS:
        return unproven(f"last measured {age} days ago, past the {EVIDENCE_MAX_AGE_DAYS}-day expiry", ev)

    bound = wilson_lower_bound(ev.passes, ev.trials)

    if ev.trials < AUTOFIX_MIN_TRIALS:
        return FixConfidence(
            rule_id=key,
            tier=TIER_MEASURED_WEAK,
            reason=(
                f"{ev.passes}/{ev.trials} correct, but {AUTOFIX_MIN_TRIALS} trials are the floor — "
                f"too few runs to distinguish a good rule from a lucky one"
            ),
            trials=ev.trials,
            passes=ev.passes,
            lower_bound=bound,
        )

    if bound < AUTOFIX_LOWER_BOUND:
        return FixConfidence(
            rule_id=key,
            tier=TIER_MEASURED_WEAK,
            reason=(
                f"{ev.passes}/{ev.trials} correct — 95% lower bound {bound:.2f}, "
                f"below the {AUTOFIX_LOWER_BOUND:.2f} required for unattended fixes"
            ),
            trials=ev.trials,
            passes=ev.passes,
            lower_bound=bound,
        )

    return FixConfidence(
        rule_id=key,
        tier=TIER_PROVEN,
        reason=f"{ev.passes}/{ev.trials} correct — 95% lower bound {bound:.2f}",
        trials=ev.trials,
        passes=ev.passes,
        lower_bound=bound,
    )
