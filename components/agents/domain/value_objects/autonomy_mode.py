"""The autonomy a run executed under (ADR 0035 D5).

This is the RECORDING half of ADR 0035, and deliberately only that. The policy
decisions — what each mode permits, whether AUTONOMOUS ever raises the risk
ceiling, whether MANUAL proposes instead of refusing — are D2/D3/D4 and are still
open. Nothing here changes what any run is allowed to do.

**Why recording comes first.** ``tool_risk.py`` already documents the trap, about
risk tiers rather than modes:

    "Empty the map and every ``delete_task`` call already in the database
     retroactively reports as a ``read`` — a governance answer that changes
     because the code moved."

The same failure applies to autonomy, with more consequence. If a run's mode is
re-derived from today's workspace setting, then switching a workspace to
AUTONOMOUS on Friday makes every historical ASSIST run look autonomous, and the
question an incident review asks first — "what was this allowed to do at the
time?" — becomes unanswerable. So the mode is resolved at call time and written
to the row, exactly like the risk tier beside it.

**UNKNOWN is a real value, not a null.** Rows written before this existed carry
no mode, and they must render as UNKNOWN rather than being back-filled to a
default. Back-filling would manufacture a governance claim about runs nobody
observed — the same reason ``risk: null`` rows were never back-filled.

**MANUAL is defined here but is not yet reachable.** There is no setting that
produces it: ``resolve()`` can only return EVALUATION, AUTONOMOUS or ASSIST from
today's signals. It is in the enum because the vocabulary should be complete when
the setting lands (D2/D6), and because a reader deserves to see the full ladder.
A mode nothing can select is honest; a mode that silently means something else
is not.
"""

from __future__ import annotations

from enum import Enum


class AutonomyMode(Enum):
    """What oversight a run executed under.

    Ordered least → most permissive, with the two non-ladder values last.
    """

    #: A human initiates every run; the agent proposes rather than writes.
    #: Not yet selectable — see the module docstring.
    MANUAL = "manual"

    #: Today's behaviour. The agent executes reversible writes; irreversible
    #: actions require explicit human approval.
    ASSIST = "assist"

    #: Unattended, scheduler-initiated. Per ADR 0035 D3 this does NOT widen what
    #: the agent may do — irreversible actions still require approval — it
    #: describes who started the run and that nobody is waiting on it.
    AUTONOMOUS = "autonomous"

    #: An evaluation run (ADR 0033 D5): stricter than any of the above, since
    #: only explicitly-declared ``read`` tools execute. Recorded distinctly
    #: because calling it ASSIST would misstate what it was permitted to do.
    EVALUATION = "evaluation"

    #: Written before modes were recorded. Never assigned to a new run.
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            AutonomyMode.MANUAL: "MANUAL",
            AutonomyMode.ASSIST: "ASSIST",
            AutonomyMode.AUTONOMOUS: "AUTONOMOUS",
            AutonomyMode.EVALUATION: "EVALUATION",
            AutonomyMode.UNKNOWN: "UNKNOWN",
        }[self]

    @property
    def is_recorded(self) -> bool:
        """False only for UNKNOWN — i.e. whether this row can support a claim."""
        return self is not AutonomyMode.UNKNOWN


#: The value stored when nothing is known. Kept as a constant so callers never
#: spell the string, and a reader searching for "unknown" finds one definition.
UNRECORDED = AutonomyMode.UNKNOWN


def resolve(*, execution_mode: str | None, is_autonomous: bool) -> AutonomyMode:
    """The mode a run is executing under, from the signals available today.

    ONE mapping, in one place. The signals are already computed inside
    ``_risk_gated`` — an ``execution_mode`` on the agent config and an
    ``is_autonomous`` derived from the calling principal — and this function
    exists so that recording them never drifts from enforcing them.

    Evaluation wins over autonomy: an eval run driven by a service principal is
    still an eval run, and it is the stricter of the two, so reporting it as
    AUTONOMOUS would overstate what it could do.
    """
    if (execution_mode or "").strip().lower() == AutonomyMode.EVALUATION.value:
        return AutonomyMode.EVALUATION
    if is_autonomous:
        return AutonomyMode.AUTONOMOUS
    return AutonomyMode.ASSIST


def parse(value: str | None) -> AutonomyMode:
    """Read a stored value back, tolerating anything unexpected.

    An unrecognised string becomes UNKNOWN rather than raising: a governance
    READ must never be the thing that takes a page down, and a value we cannot
    interpret is precisely a mode we do not know.
    """
    if not value:
        return AutonomyMode.UNKNOWN
    try:
        return AutonomyMode(str(value).strip().lower())
    except ValueError:
        return AutonomyMode.UNKNOWN


__all__ = ["UNRECORDED", "AutonomyMode", "parse", "resolve"]
