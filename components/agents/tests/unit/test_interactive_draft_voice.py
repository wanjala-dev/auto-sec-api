"""Unit tests: brand-voice steering in the interactive draft use case (SEE-172).

Verifies the voice style card reaches the generation prompt AND is kept OUT of
the faithfulness grounding set (voice steers HOW copy reads; it is never a
fact). Pure logic with in-memory fakes — no DB, no LLM, no infra.
"""

from __future__ import annotations

import json

import pytest

from components.agents.application.use_cases.generate_interactive_draft_use_case import (
    GenerateInteractiveDraftUseCase,
)

pytestmark = pytest.mark.unit


class _Chunk:
    def __init__(self, content: str) -> None:
        self.content = content
        self.metadata = {"section_title": "Story"}
        self.score = 0.9


class _FakeRetrieval:
    def __init__(self, chunks):
        self._chunks = chunks

    def search(self, *, workspace_id, query, k=5):
        return self._chunks


class _CapturingLlm:
    """Captures the prompt it was asked to generate from."""

    def __init__(self):
        self.prompt = None

    def invoke(self, prompt, **kwargs):
        self.prompt = prompt

        class _Resp:
            content = json.dumps({"title": "T", "body_html": "<p>grounded body</p>"})

        return _Resp()


class _FakeVoicePort:
    def __init__(self, card: str):
        self._card = card

    def style_card(self, *, workspace_id: str) -> str:
        return self._card


_VOICE_CARD = (
    "VOICE & STYLE PROFILE (apply to HOW the copy reads — these are style "
    "rules, NOT facts):\n- Voice: heartfelt, plain-spoken\n"
)


class TestInteractiveDraftVoice:
    def _run(self, *, voice_port):
        llm = _CapturingLlm()
        use_case = GenerateInteractiveDraftUseCase(
            retrieval_port=_FakeRetrieval([_Chunk("We served 14 people this term.")]),
            llm_port=llm,
            fact_sheet_port=None,
            voice_profile_port=voice_port,
        )
        result = use_case.execute(
            workspace_id="w1", kind="letter", context={"title": "Thank you"}
        )
        return llm, result

    def test_voice_card_injected_into_prompt(self):
        llm, _ = self._run(voice_port=_FakeVoicePort(_VOICE_CARD))
        assert "VOICE & STYLE PROFILE" in llm.prompt
        assert "heartfelt, plain-spoken" in llm.prompt

    def test_voice_card_excluded_from_faithfulness_grounding(self):
        # The grounding set the verifier checks against must contain the RAG
        # chunk text but NOT the voice card — otherwise voice adjectives would
        # be mistaken for verifiable facts.
        chunks = [_Chunk("We served 14 people this term.")]
        texts = GenerateInteractiveDraftUseCase._grounding_texts(
            chunks=chunks, fact_sheet={}
        )
        joined = "\n".join(texts)
        assert "We served 14 people" in joined
        assert "VOICE & STYLE PROFILE" not in joined
        assert "heartfelt" not in joined

    def test_no_voice_port_still_generates(self):
        # Voice is enrichment, never a hard dependency.
        llm, result = self._run(voice_port=None)
        assert "VOICE & STYLE PROFILE" not in (llm.prompt or "")
        assert result["body_html"]

    def test_empty_voice_card_omits_block(self):
        llm, _ = self._run(voice_port=_FakeVoicePort(""))
        assert "VOICE & STYLE PROFILE" not in llm.prompt

    def test_voice_port_failure_does_not_break_drafting(self):
        class _Boom:
            def style_card(self, *, workspace_id):
                raise RuntimeError("voice store down")

        llm, result = self._run(voice_port=_Boom())
        # best-effort: generation still happens, no voice block
        assert result["body_html"]
        assert "VOICE & STYLE PROFILE" not in (llm.prompt or "")
