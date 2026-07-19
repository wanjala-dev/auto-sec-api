"""Context Recall — set comparison against `expected_sections`.

RAGAS §3.3 defines Context Recall as the fraction of *relevant* chunks
the retriever actually returned. The original RAGAS uses an LLM to
score each ground-truth chunk against the retrieved set; our eval set
encodes ground truth as `expected_sections` (which snapshot section
keys SHOULD have been retrieved), so the comparison is purely
deterministic — no LLM needed.

A retrieved chunk's section is read from `chunk.metadata.section`
(set by the snapshot builder). Each section in `expected_sections`
that appears in the retrieved chunks' section set counts as recalled.

Score = |expected_sections ∩ retrieved_sections| / |expected_sections|

Edge case: `expected_sections` empty (e.g. multi-route prompts where
no specific section is required) → return 1.0 (vacuously perfect).
Otherwise a multi-route prompt would always score 0 and pollute the
aggregate.

Reference: Es, S. et al. (2023) RAGAS §3.3.
"""
from __future__ import annotations

from typing import Sequence

from tests.eval.rag.metrics import MetricResult


class ContextRecall:
    name = "context_recall"

    def score(
        self,
        *,
        prompt_id: str,
        expected_sections: Sequence[str],
        retrieved_chunks: Sequence[dict],
    ) -> MetricResult:
        """Compute Context Recall.

        Args:
            prompt_id: For logging; not used in the math.
            expected_sections: Ground-truth section keys that should
                be in the retrieved chunks (from eval_set.yaml).
            retrieved_chunks: Chunks the pipeline actually returned.
                Each chunk is a dict with a `metadata` key whose value
                is a dict containing `section`.

        Returns:
            MetricResult with score in [0, 1] and detail listing which
            expected sections were matched vs missing.
        """
        expected = set(expected_sections)
        if not expected:
            return MetricResult(
                name=self.name,
                score=1.0,
                detail={
                    "expected_sections": [],
                    "retrieved_sections": sorted(_retrieved_sections(retrieved_chunks)),
                    "reason": "empty expected_sections → vacuously perfect",
                },
            )

        retrieved = _retrieved_sections(retrieved_chunks)
        matched = expected & retrieved
        missing = expected - retrieved
        return MetricResult(
            name=self.name,
            score=len(matched) / len(expected),
            detail={
                "expected_sections": sorted(expected),
                "retrieved_sections": sorted(retrieved),
                "matched_sections": sorted(matched),
                "missing_sections": sorted(missing),
            },
        )


def _retrieved_sections(chunks: Sequence[dict]) -> set[str]:
    """Pull the `section` value out of each chunk's metadata.

    Chunks may come from different sources (snapshot, documents) with
    slightly different metadata shapes. Be defensive — a missing
    `section` is recorded as `unknown` so it counts but doesn't crash.
    """
    sections: set[str] = set()
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        section = metadata.get("section") or "unknown"
        sections.add(str(section))
    return sections
