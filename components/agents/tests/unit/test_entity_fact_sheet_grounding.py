"""Unit tests for per-entity fact-sheet grounding (SEE-170).

Pure application-layer tests: the fact-sheet dependency is an in-memory
fake implementing ``EntityFactSheetPort``. They prove that an
entity-update draft (a) fetches the linked entity's real data, (b) injects
those figures into the LLM prompt, (c) counts them as supported by the
faithfulness check, and (d) infers the entity type from the kind when the
caller omits ``related_entity_type``. No DB, no LLM, no infrastructure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from components.agents.application.use_cases.generate_interactive_draft_use_case import (
    GenerateInteractiveDraftUseCase,
)


@dataclass
class _Chunk:
    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


@dataclass
class _LlmResponse:
    content: str


class _FakeRetrieval:
    def __init__(self, chunks=None):
        self._chunks = chunks or []

    def search(self, *, workspace_id, query, k=5):
        return list(self._chunks)


class _FakeLlm:
    def __init__(self, response_content):
        self._response = response_content
        self.prompts = []

    def invoke(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return _LlmResponse(content=self._response)


class _FakeFactSheet:
    """In-memory ``EntityFactSheetPort``."""

    def __init__(self, sheet):
        self._sheet = sheet
        self.calls = []

    def fact_sheet(self, *, workspace_id, entity_type, entity_id):
        self.calls.append(
            {"workspace_id": workspace_id, "entity_type": entity_type, "entity_id": entity_id}
        )
        return dict(self._sheet)


def _use_case(*, sheet, llm_content, chunks=None):
    retrieval = _FakeRetrieval(chunks)
    llm = _FakeLlm(llm_content)
    fact_sheet = _FakeFactSheet(sheet)
    uc = GenerateInteractiveDraftUseCase(
        retrieval_port=retrieval, llm_port=llm, fact_sheet_port=fact_sheet
    )
    return uc, llm, fact_sheet


_AMINA_SHEET = {
    "entity_type": "recipient",
    "entity_id": "rec-1",
    "name": "Amina Hassan",
    "facts": [
        "Name: Amina Hassan",
        "Age: 12",
        "Location: Kisumu",
        "Total raised: 45000.00",
    ],
}


class TestFactSheetInPrompt:
    def test_entity_facts_injected_into_prompt(self):
        uc, llm, fact_sheet = _use_case(
            sheet=_AMINA_SHEET,
            llm_content=json.dumps({"title": "T", "body_html": "<p>x</p>"}),
        )

        uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={
                "title": "Amina term update",
                "related_entity_type": "recipient",
                "related_entity_id": "rec-1",
            },
        )

        prompt = llm.prompts[0]
        assert "LINKED RECORD" in prompt
        assert "Amina Hassan" in prompt
        assert "Age: 12" in prompt
        assert "Total raised: 45000.00" in prompt
        # the port was asked for the right entity
        assert fact_sheet.calls == [
            {"workspace_id": "ws-1", "entity_type": "recipient", "entity_id": "rec-1"}
        ]


class TestFactSheetCountsAsSupported:
    def test_entity_figures_count_as_grounding_for_faithfulness(self):
        # The body uses figures that exist ONLY in the fact sheet (no RAG
        # chunks at all). They must count as supported.
        uc, _, _ = _use_case(
            sheet=_AMINA_SHEET,
            chunks=[],
            llm_content=json.dumps(
                {
                    "title": "T",
                    "body_html": "<p>Amina, age 12, has raised 45,000 so far.</p>",
                }
            ),
        )

        result = uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={
                "related_entity_type": "recipient",
                "related_entity_id": "rec-1",
            },
        )

        assert result["faithfulness"]["ok"] is True
        assert result["faithfulness"]["unsupported_numbers"] == []

    def test_figure_not_in_sheet_or_chunks_still_flagged(self):
        uc, _, _ = _use_case(
            sheet=_AMINA_SHEET,
            chunks=[],
            llm_content=json.dumps(
                {"title": "T", "body_html": "<p>Amina raised 99,999.</p>"}
            ),
        )

        result = uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={
                "related_entity_type": "recipient",
                "related_entity_id": "rec-1",
            },
        )

        assert result["faithfulness"]["ok"] is False
        assert any("99,999" in n for n in result["faithfulness"]["unsupported_numbers"])


class TestEntityTypeInference:
    def test_type_inferred_from_kind_when_omitted(self):
        uc, _, fact_sheet = _use_case(
            sheet=_AMINA_SHEET,
            llm_content=json.dumps({"body_html": "<p>x</p>"}),
        )

        uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={"related_entity_id": "rec-1"},  # no related_entity_type
        )

        assert fact_sheet.calls[0]["entity_type"] == "recipient"


class TestNoneSafety:
    def test_missing_port_does_not_crash(self):
        retrieval = _FakeRetrieval([])
        llm = _FakeLlm(json.dumps({"body_html": "<p>x</p>"}))
        uc = GenerateInteractiveDraftUseCase(
            retrieval_port=retrieval, llm_port=llm  # no fact_sheet_port
        )

        result = uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={"related_entity_type": "recipient", "related_entity_id": "rec-1"},
        )

        # no crash, faithfulness still attached, and no entity facts injected
        assert "faithfulness" in result
        assert "Amina Hassan" not in llm.prompts[0]

    def test_no_linked_entity_skips_fact_sheet(self):
        uc, llm, fact_sheet = _use_case(
            sheet=_AMINA_SHEET, llm_content=json.dumps({"body_html": "<p>x</p>"})
        )

        uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        assert fact_sheet.calls == []
        assert "Amina Hassan" not in llm.prompts[0]
