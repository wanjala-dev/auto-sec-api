"""The seams an evaluation run depends on (ADR 0033).

Four ports, each isolating something the runner must not know the shape of:

- ``CaseSourcePort``   — where cases come from (mined history, curated suite)
- ``AgentRunnerPort``  — how a case is executed against the agent under test
- ``JudgePort``        — how a judged axis is graded
- ``VerifierPort``     — how a deterministic axis is checked

Splitting the judge from the verifier is not ceremony. ADR 0033 D2 says a check
that can be mechanical MUST be mechanical: ``fix_applies`` and
``no_fabricated_asset`` are answerable in code, and asking an LLM instead would
spend tokens to obtain a less reliable answer. Two ports keeps that division
enforceable rather than aspirational.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCaseInput:
    """One case, as the runner sees it."""

    case_id: str
    scenario: str
    prompt_inputs: dict
    solution_criteria: list[str] = field(default_factory=list)
    label: str = "unlabelled"


@dataclass(frozen=True)
class AgentOutcome:
    """What the agent produced for a case, plus where to find the evidence."""

    output: str
    deep_run_id: str | None = None
    cost_usd: float = 0.0
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)


@dataclass(frozen=True)
class AxisVerdict:
    """One axis's result for one case.

    ``passed=None`` means NOT MEASURED — the axis was not assessed. It is not a
    failure, and rendering it as one is the specific dishonesty ADR 0032 and
    #415 exist to prevent.
    """

    axis: str
    passed: bool | None
    reason: str = ""


@dataclass(frozen=True)
class JudgeVerdict:
    """A judged grading, structured so reasoning precedes the verdict.

    Field ORDER is load-bearing. Both the research (inter-judge kappa 0.55 ->
    0.75) and Anthropic's own course material ("without this context, models
    default to middling scores around 6") say the judge must reason before it
    grades. The prompt asks for strengths, weaknesses and reasoning first, and
    the verdicts last, so the model cannot anchor on a score it then justifies.
    """

    strengths: list[str]
    weaknesses: list[str]
    reasoning: str
    verdicts: dict[str, bool]
    model_slug: str = ""
    cost_usd: float = 0.0


class CaseSourcePort(ABC):
    @abstractmethod
    def load_cases(self, *, suite_id: str, workspace_id: str) -> list[EvalCaseInput]:
        """Every case in a suite, scoped to one workspace."""


class AgentRunnerPort(ABC):
    @abstractmethod
    def run_case(self, *, agent_type: str, workspace_id: str, case: EvalCaseInput, model_slug: str) -> AgentOutcome:
        """Execute one case against the agent under test.

        The implementation MUST run in evaluation mode (ADR 0033 D5) so the
        agent cannot mutate the workspace it is being measured against.
        """


class JudgePort(ABC):
    @abstractmethod
    def grade(self, *, case: EvalCaseInput, outcome: AgentOutcome, axes: list[str], model_slug: str) -> JudgeVerdict:
        """Grade the judged axes for one case."""


class VerifierPort(ABC):
    @abstractmethod
    def supports(self, axis: str) -> bool:
        """Whether this axis can be checked deterministically."""

    @abstractmethod
    def verify(self, *, axis: str, case: EvalCaseInput, outcome: AgentOutcome) -> AxisVerdict:
        """Check one deterministic axis. Never raises — returns a failed verdict."""


__all__ = [
    "AgentOutcome",
    "AgentRunnerPort",
    "AxisVerdict",
    "CaseSourcePort",
    "EvalCaseInput",
    "JudgePort",
    "JudgeVerdict",
    "VerifierPort",
]
