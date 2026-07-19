"""RAGAS-style metrics for the RAG eval harness.

Four metrics, each in its own module, each returning a float in [0, 1]
where 1.0 is a perfect run.

Formulas follow Es, S. et al. (2023) *RAGAS: Automated Evaluation of
Retrieval Augmented Generation* (arxiv 2309.15217). Each module docstring
cites the specific section of the paper it implements.

The metrics call out to a `JudgeLLM` protocol so the harness stays
provider-agnostic — we feed it our `AILlmProvider` port adapter in the
runner, but tests can pass a deterministic fake.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricResult:
    """One metric's outcome for one eval prompt.

    `score` is the [0, 1] metric value. `detail` is whatever debug info
    the metric chose to surface — claims extracted, chunks judged, etc.
    Useful when the report renders a per-prompt breakdown.
    """

    name: str
    score: float
    detail: dict

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                f"MetricResult.score must be in [0, 1]; got {self.score}"
            )


from tests.eval.rag.metrics.answer_relevancy import AnswerRelevancy  # noqa: E402
from tests.eval.rag.metrics.context_precision import ContextPrecision  # noqa: E402
from tests.eval.rag.metrics.context_recall import ContextRecall  # noqa: E402
from tests.eval.rag.metrics.faithfulness import Faithfulness  # noqa: E402

__all__ = [
    "MetricResult",
    "AnswerRelevancy",
    "ContextPrecision",
    "ContextRecall",
    "Faithfulness",
]
