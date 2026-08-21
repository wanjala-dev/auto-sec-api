"""The identity of the exact set of cases a run was scored against (ADR 0033 D13).

An eval score means nothing without the dataset version behind it. That is the
one point the practitioner literature is unanimous on, and the reason is not
bookkeeping — it is that **a change to the dataset is indistinguishable from a
change to the model** unless something records which rows were involved. Fix a
typo in one case, re-run, watch the score move, and conclude the agent
regressed. Two runs "on the same suite" can quietly have run different rows.

Mining hid this problem, because history only ever appends. Letting people
author and edit their own cases is what makes it acute.

So a run stores a FINGERPRINT of its cases, computed here:

* It covers the case CONTENT, not just the ids. A case whose expected criteria
  were rewritten is a different question even though its primary key did not
  move — and rewriting the criteria is the single easiest way to make a failing
  suite pass.
* It is order-independent. Cases are sorted by id first, so re-ordering a suite
  is correctly a no-op rather than a false "dataset changed".
* It is stable across processes and machines: `json.dumps(..., sort_keys=True)`
  then SHA-256, no `hash()`, which is salted per interpreter.

What the product does with it is refuse to draw a comparison it cannot support.
Two runs with different fingerprints are two different exams, and the panel says
so instead of drawing a trend line between them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

#: Enough hex to identify a dataset in a UI without being a wall of characters.
#: 12 hex chars is 48 bits — collision risk is irrelevant at the scale of one
#: workspace's suites, and it stays readable in a table cell.
SHORT_LENGTH = 12


@dataclass(frozen=True)
class CaseFingerprintInput:
    """The parts of a case that change what is being ASKED.

    Deliberately not every column. `created_at` and the row's own bookkeeping
    do not change the question, and including them would report a dataset as
    changed every time a case was touched for an unrelated reason — which would
    train people to ignore the signal.
    """

    case_id: str
    scenario: str
    prompt_inputs: dict
    solution_criteria: list[str]


def fingerprint(cases: list[CaseFingerprintInput], *, system_prompt: str = "") -> str:
    """A stable SHA-256 over the content of a case set.

    ``system_prompt`` participates for PROMPT-mode suites, where the prompt is
    not configuration around the question — it IS the thing under test. Leaving
    it out would let someone rewrite the prompt, re-run, and read the movement
    as the model changing, which is the exact confusion this function exists to
    prevent. Agent-mode suites pass nothing and are unaffected.
    """
    payload = [
        {
            "id": str(case.case_id),
            "scenario": case.scenario or "",
            "prompt_inputs": case.prompt_inputs or {},
            "solution_criteria": list(case.solution_criteria or []),
        }
        for case in sorted(cases, key=lambda c: str(c.case_id))
    ]
    encoded = json.dumps(
        {"cases": payload, "system_prompt": system_prompt or ""},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def short(value: str) -> str:
    """The display form. Empty stays empty — a run from before fingerprints
    existed has no version, and inventing one would be worse than showing none."""
    return (value or "")[:SHORT_LENGTH]


def comparable(left: str, right: str) -> bool:
    """Whether two runs' scores may be put side by side.

    An unknown fingerprint on either side is NOT comparable. Runs recorded
    before this existed carry no version, and treating "we do not know" as "the
    same" is precisely the false comparison the fingerprint exists to prevent.
    """
    if not left or not right:
        return False
    return left == right


__all__ = ["SHORT_LENGTH", "CaseFingerprintInput", "comparable", "fingerprint", "short"]
