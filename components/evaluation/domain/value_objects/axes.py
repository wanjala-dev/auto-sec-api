"""The axes a triage-agent answer is graded on (ADR 0033 D2).

An axis is one binary question about one answer. Five of them, chosen to be
non-overlapping and — the part that is easy to get wrong — each independently
FAILABLE. An axis no case can fail is not an axis; it is decoration that
inflates a pass rate.

The load-bearing property here is the **grader split**. Two of the five are
mechanical, so they are answered by code:

    fix_applies          a patch either parses and targets real files, or it does not
    no_fabricated_asset  a URN either appears in the workspace's inventory, or it does not

The other three are judgements about meaning, so they go to the LLM judge. That
division is not a preference. The Anthropic course material maps *format* and
*valid syntax* onto code graders and *task following* onto model graders for the
same reason, and ADR 0033 D2 states it as a rule: prefer a verifier to a judge
wherever the check can be mechanical. A deterministic axis costs no tokens,
cannot drift with judge mood, has no rubric to be ambiguous, and is not subject
to D6's agreement machinery at all — every one we can move out of the judge's
hands makes the remaining rubric cheaper AND more trustworthy.

Two notes on shape:

* This module declares the vocabulary; it does not evaluate anything. The
  deterministic checks live in ``domain/services/verifiers.py`` and the judged
  ones in the rubric prompt. Keeping the vocabulary separate is what lets
  ``EvalSuite.axes`` store keys that both sides agree on.
* The domain layer imports NOTHING — no Django, no other bounded context. The
  architecture suite enforces it and caught exactly that mistake in the first
  draft of ``claim_tier.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Grader(Enum):
    """Who answers an axis.

    Named after the course material's three grader kinds. HUMAN is deliberately
    absent: a human grader is a calibration input (D6a), not something an
    automated run can dispatch to, and declaring it here would invite a suite
    that silently reports NOT MEASURED forever while looking configured.
    """

    #: Answered in code. No tokens, no rubric, no judge disagreement.
    DETERMINISTIC = "deterministic"
    #: Answered by the LLM judge against the case's ``solution_criteria``.
    JUDGED = "judged"


@dataclass(frozen=True)
class Axis:
    """One binary question, and who is qualified to answer it."""

    key: str
    label: str
    description: str
    grader: Grader

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("axis key cannot be empty")
        if not self.label or not self.label.strip():
            raise ValueError(f"axis {self.key!r} has no human label")
        if not self.description or not self.description.strip():
            # A judged axis with no description is a rubric the judge has to
            # invent, which is precisely the ambiguity D6 exists to detect.
            raise ValueError(f"axis {self.key!r} has no description")

    @property
    def is_deterministic(self) -> bool:
        return self.grader is Grader.DETERMINISTIC

    @property
    def requires_judge(self) -> bool:
        """True when grading this axis costs an LLM call.

        Callers use this to estimate spend BEFORE the run (D7), so it must stay
        the exact complement of ``is_deterministic`` — a third state here would
        become a case that is silently never graded.
        """
        return self.grader is Grader.JUDGED

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "grader": self.grader.value,
            "is_deterministic": self.is_deterministic,
        }


GROUNDED = Axis(
    key="grounded",
    label="Grounded",
    description="Every artifact the answer cites exists and says what the answer claims it says.",
    grader=Grader.JUDGED,
)

SEVERITY_SOUND = Axis(
    key="severity_sound",
    label="Severity sound",
    description="The severity the answer assigns matches the exposure and impact the case actually describes.",
    grader=Grader.JUDGED,
)

FIX_APPLIES = Axis(
    key="fix_applies",
    label="Fix applies",
    description="The produced patch parses as a unified diff and targets files that exist at the target revision.",
    grader=Grader.DETERMINISTIC,
)

SCOPE_RESPECTED = Axis(
    key="scope_respected",
    label="Scope respected",
    description="The answer stays inside what the case authorises and declines anything beyond it.",
    grader=Grader.JUDGED,
)

NO_FABRICATED_ASSET = Axis(
    key="no_fabricated_asset",
    label="No fabricated asset",
    description="Every asset or URN the answer references resolves in this workspace's inventory.",
    grader=Grader.DETERMINISTIC,
)

#: The starting axis set for the triage agent, in ADR 0033 D2's order.
#:
#: Stored on ``EvalSuite.axes`` per suite rather than read globally at grade
#: time, so adding a sixth axis later does not silently rewrite the meaning of
#: results already recorded under these five.
TRIAGE_AXES: tuple[Axis, ...] = (
    GROUNDED,
    SEVERITY_SOUND,
    FIX_APPLIES,
    SCOPE_RESPECTED,
    NO_FABRICATED_ASSET,
)

_BY_KEY: dict[str, Axis] = {axis.key: axis for axis in TRIAGE_AXES}

#: Convenience for suite creation and for asserting a stored suite's axes.
TRIAGE_AXIS_KEYS: tuple[str, ...] = tuple(_BY_KEY)


def axis_for(key: str) -> Axis:
    """Look an axis up by key.

    Raises rather than returning ``None``: an unknown axis key reaching the
    grader means a suite and the code disagree about what is being measured,
    and the honest outcome of that is a loud failure, not a quietly ungraded
    axis that renders as a pass.
    """
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"unknown evaluation axis {key!r}; known axes: {list(_BY_KEY)}") from None


def deterministic_axes() -> tuple[Axis, ...]:
    """The axes answered in code — no judge, no tokens (D2)."""
    return tuple(axis for axis in TRIAGE_AXES if axis.is_deterministic)


def judged_axes() -> tuple[Axis, ...]:
    """The axes that need the LLM judge, and therefore cost money (D7)."""
    return tuple(axis for axis in TRIAGE_AXES if axis.requires_judge)


__all__ = [
    "FIX_APPLIES",
    "GROUNDED",
    "NO_FABRICATED_ASSET",
    "SCOPE_RESPECTED",
    "SEVERITY_SOUND",
    "TRIAGE_AXES",
    "TRIAGE_AXIS_KEYS",
    "Axis",
    "Grader",
    "axis_for",
    "deterministic_axes",
    "judged_axes",
]
