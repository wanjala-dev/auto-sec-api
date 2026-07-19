"""Unit tests for the SEE-173 writing-eval deterministic graders.

Pure logic — no LLM, no DB. Covers the readability service, the four code
graders (faithfulness / voice / readability / structure), the aggregator,
and the golden dataset's shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.agents.domain.services.readability import score_readability
from components.agents.tests.prompt_eval.graders.writing import (
    grade_writing_with_code,
)
from components.agents.tests.prompt_eval.graders.writing.code_graders import (
    grade_faithfulness,
    grade_readability,
    grade_structure,
    grade_voice,
)


def _case(facts=None, voice=None, kind="letter"):
    return {
        "id": "c",
        "category": kind,
        "kind": kind,
        "context": {
            "kind": kind,
            "retrieved_context": facts or [],
            "voice": voice or {},
        },
    }


def _draft(body, title="A title", sections=None):
    return {"title": title, "body_html": body, "sections": sections or []}


class TestReadability:
    def test_plain_english_scores_higher_than_dense(self):
        plain = score_readability("We helped kids read. They are happy now.")
        dense = score_readability(
            "The organization facilitated multidimensional literacy "
            "interventions yielding substantial pedagogical advancement."
        )
        assert plain.flesch_reading_ease > dense.flesch_reading_ease

    def test_empty_text_is_worst(self):
        r = score_readability("")
        assert r.word_count == 0
        assert r.flesch_reading_ease == 0.0

    def test_strips_html(self):
        r = score_readability("<p>We raised funds.</p>")
        assert r.word_count == 3


class TestFaithfulnessGrader:
    def test_grounded_figures_pass(self):
        case = _case(facts=["We raised $5,000 from 12 gifts for 48 readers."])
        draft = _draft("<p>This month we raised $5,000 from 12 gifts for 48 readers.</p>")
        result = grade_faithfulness(draft, case)
        assert result.score == 10
        assert result.reasons == []

    def test_fabricated_figure_flagged(self):
        case = _case(facts=["We raised $5,000."])
        draft = _draft("<p>We raised $80,000 this month.</p>")
        result = grade_faithfulness(draft, case)
        assert result.score < 10
        assert any("80" in r for r in result.reasons)

    def test_empty_draft_scores_zero(self):
        result = grade_faithfulness(_draft(""), _case(facts=["$5,000"]))
        assert result.score == 0


class TestVoiceGrader:
    def test_no_rules_is_neutral_pass(self):
        result = grade_voice(_draft("<p>We helped children read.</p>"), _case())
        assert result.score == 10

    def test_banned_term_flagged(self):
        case = _case(voice={"banned_terms": ["child", "children"], "preferred": "young readers"})
        result = grade_voice(_draft("<p>We helped children read.</p>"), case)
        assert result.score < 10
        assert any("children" in r for r in result.reasons)

    def test_preferred_term_passes(self):
        case = _case(voice={"banned_terms": ["child", "children"], "preferred": "young readers"})
        result = grade_voice(_draft("<p>We helped young readers read.</p>"), case)
        assert result.score == 10

    def test_banned_term_is_whole_word(self):
        # "childcare" must NOT trip the "child" rule.
        case = _case(voice={"banned_terms": ["child"]})
        result = grade_voice(_draft("<p>We fund childcare programs.</p>"), case)
        assert result.score == 10


class TestReadabilityGrader:
    def test_plain_copy_scores_high(self):
        draft = _draft("<p>We helped readers. They are happy. Thank you for your gift.</p>")
        assert grade_readability(draft, _case()).score >= 8

    def test_empty_draft_scores_zero(self):
        assert grade_readability(_draft(""), _case()).score == 0


class TestStructureGrader:
    def test_full_draft_passes(self):
        body = "<p>" + " ".join(["word"] * 30) + "</p>"
        assert grade_structure(_draft(body), _case()).score == 10

    def test_missing_title_deducts(self):
        body = "<p>" + " ".join(["word"] * 30) + "</p>"
        result = grade_structure(_draft(body, title=""), _case())
        assert result.score < 10
        assert any("title" in r for r in result.reasons)

    def test_newsletter_without_sections_deducts(self):
        body = "<p>" + " ".join(["word"] * 30) + "</p>"
        case = _case(kind="newsletter")
        result = grade_structure(_draft(body, sections=[]), case)
        assert any("section" in r for r in result.reasons)

    def test_empty_body_scores_zero(self):
        assert grade_structure(_draft(""), _case()).score == 0


class TestAggregate:
    def test_aggregates_subscores(self):
        case = _case(facts=["We raised $5,000."], voice={"banned_terms": ["child"]})
        body = "<p>" + " ".join(["word"] * 30) + " We raised $5,000.</p>"
        agg = grade_writing_with_code(_draft(body), case)
        assert 0 <= agg.overall_score <= 10
        labels = {s.label for s in agg.sub_scores}
        assert labels == {"faithfulness", "voice", "readability", "structure"}


class TestDataset:
    def test_writing_v1_is_well_formed(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "prompt_eval" / "datasets" / "writing_v1.json"
        )
        data = json.loads(path.read_text())
        cases = data.get("cases") or []
        assert cases, "writing_v1 must have cases"
        for case in cases:
            assert case.get("id")
            ctx = case.get("context") or {}
            assert ctx.get("kind"), f"{case.get('id')} missing context.kind"
            assert ctx.get("retrieved_context"), f"{case.get('id')} missing grounding facts"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
