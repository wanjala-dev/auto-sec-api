"""Unit tests for ``GenerateInteractiveDraftUseCase`` (SEE-169).

Pure application-layer tests: both ports are in-memory fakes, no DB, no
LLM, no infrastructure. Proves grounding (retrieved context + document
title land in the prompt), generation (body comes from the LLM port),
and the non-persistence guarantee (the use case has no way to touch the
ORM — it depends only on the two injected ports).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from components.agents.application.use_cases.generate_interactive_draft_use_case import (
    GenerateInteractiveDraftUseCase,
)


@dataclass
class _Chunk:
    """Duck-typed stand-in for ``RetrievedChunk``."""

    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


@dataclass
class _LlmResponse:
    content: str


class _FakeRetrieval:
    """Captures the query and returns a fixed chunk list."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def search(self, *, workspace_id, query, k=5):
        self.calls.append({"workspace_id": workspace_id, "query": query, "k": k})
        return list(self._chunks)


class _FakeLlm:
    """Captures the prompt and returns a scripted response."""

    def __init__(self, response_content):
        self._response = response_content
        self.prompts = []

    def invoke(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return _LlmResponse(content=self._response)


def _use_case(*, chunks=None, llm_content="{}"):
    retrieval = _FakeRetrieval(chunks or [])
    llm = _FakeLlm(llm_content)
    uc = GenerateInteractiveDraftUseCase(retrieval_port=retrieval, llm_port=llm)
    return uc, retrieval, llm


class TestGrounding:
    def test_prompt_includes_retrieved_context_and_document_title(self):
        chunks = [
            _Chunk(
                content="The Mastercard Foundation gave $50,000 to the literacy program.",
                metadata={"section_title": "Grants"},
                score=0.9,
            ),
        ]
        uc, retrieval, llm = _use_case(
            chunks=chunks,
            llm_content=json.dumps({"title": "Thank you", "body_html": "<p>Hi</p>"}),
        )

        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={
                "title": "Thank-you letter to Mastercard Foundation",
                "prompt": "thank them for the grant",
                "recipient_name": "Mastercard Foundation",
            },
        )

        assert llm.prompts, "LLM should have been invoked"
        prompt = llm.prompts[0]
        # (b) retrieved RAG context is in the prompt as grounding
        assert "The Mastercard Foundation gave $50,000" in prompt
        assert "WORKSPACE CONTEXT" in prompt
        # (b) the document is document-aware — its title is in the prompt
        assert "Thank-you letter to Mastercard Foundation" in prompt
        # grounding guardrail instruction present (slot-and-verify framing)
        assert "never invent" in prompt.lower() or "do not invent" in prompt.lower()

    def test_seed_query_combines_title_kind_and_prompt(self):
        uc, retrieval, llm = _use_case(llm_content="{}")

        uc.execute(
            workspace_id="ws-1",
            kind="recipient_update",
            context={"title": "Amina progress", "prompt": "school term recap"},
        )

        assert retrieval.calls, "retrieval should have been queried"
        query = retrieval.calls[0]["query"]
        assert "Amina progress" in query
        assert "recipient update" in query  # kind, underscores → spaces
        assert "school term recap" in query

    def test_empty_retrieval_still_generates_and_notes_no_context(self):
        uc, retrieval, llm = _use_case(
            chunks=[],
            llm_content=json.dumps({"title": "T", "body_html": "<p>b</p>"}),
        )

        result = uc.execute(workspace_id="ws-1", kind="summary", context={"title": "Q1 summary"})

        assert "none found" in llm.prompts[0]
        assert result["source_chunks"] == []
        assert result["body_html"] == "<p>b</p>"


class TestGeneration:
    def test_returns_body_from_llm_json(self):
        uc, retrieval, llm = _use_case(
            llm_content=json.dumps({"title": "Spring news", "body_html": "<h2>Hi</h2><p>Body</p>"})
        )

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        assert result["title"] == "Spring news"
        assert result["body_html"] == "<h2>Hi</h2><p>Body</p>"
        assert result["agent_type"] == "writing_agent"

    def test_plain_prose_response_surfaces_as_body(self):
        uc, retrieval, llm = _use_case(llm_content="Just some prose, no JSON.")

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        assert result["body_html"] == "Just some prose, no JSON."

    def test_blog_kind_passes_excerpt_through(self):
        uc, retrieval, llm = _use_case(
            llm_content=json.dumps({"title": "Story", "excerpt": "A teaser", "body_html": "<p>x</p>"})
        )

        result = uc.execute(workspace_id="ws-1", kind="blog", context={"topic": "literacy"})

        assert result["excerpt"] == "A teaser"

    def test_newsletter_kind_passes_sections_through(self):
        sections = [{"heading": "Highlights", "body_html": "<p>h</p>"}]
        uc, retrieval, llm = _use_case(
            llm_content=json.dumps({"title": "Newsletter", "body_html": "<p>b</p>", "sections": sections})
        )

        result = uc.execute(workspace_id="ws-1", kind="newsletter", context={"title": "May news"})

        assert result["sections"] == sections

    def test_source_chunks_serialised_for_provenance(self):
        chunks = [
            _Chunk(content="fact one", metadata={"section_title": "Donations"}, score=0.8),
        ]
        uc, retrieval, llm = _use_case(chunks=chunks, llm_content=json.dumps({"title": "T", "body_html": "<p>b</p>"}))

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        assert result["source_chunks"] == [
            {
                "section": "",
                "section_title": "Donations",
                "content": "fact one",
                "score": 0.8,
            }
        ]

    def test_llm_failure_returns_empty_body_not_exception(self):
        class _BoomLlm:
            def invoke(self, prompt, **kwargs):
                raise RuntimeError("LLM down")

        uc = GenerateInteractiveDraftUseCase(retrieval_port=_FakeRetrieval([]), llm_port=_BoomLlm())

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        # Falls back to the document title; never raises.
        assert result["title"] == "Doc"
        assert result["body_html"] == ""


class TestFaithfulnessWiring:
    """SEE-171: the use case attaches a faithfulness report and surfaces
    unverified figures rather than silently stripping them."""

    def test_fabricated_number_flips_ok_false(self):
        chunks = [_Chunk(content="The grant was $50,000.", score=0.9)]
        uc, _, _ = _use_case(
            chunks=chunks,
            llm_content=json.dumps({"title": "T", "body_html": "<p>We received $90,000.</p>"}),
        )

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        faith = result["faithfulness"]
        assert faith["ok"] is False
        assert any("90,000" in n for n in faith["unsupported_numbers"])
        assert faith["checked"] >= 1

    def test_grounded_numbers_are_ok(self):
        chunks = [_Chunk(content="The grant was $50,000 for 12 children.", score=0.9)]
        uc, _, _ = _use_case(
            chunks=chunks,
            llm_content=json.dumps({"title": "T", "body_html": "<p>We received $50,000 for 12 kids.</p>"}),
        )

        result = uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})

        assert result["faithfulness"]["ok"] is True
        assert result["faithfulness"]["unsupported_numbers"] == []

    def test_faithfulness_block_always_present(self):
        uc, _, _ = _use_case(llm_content=json.dumps({"body_html": "<p>hi</p>"}))
        result = uc.execute(workspace_id="ws-1", kind="letter", context={})
        assert set(result["faithfulness"]) == {
            "ok",
            "unsupported_numbers",
            "unsupported_names",
            "checked",
        }

    def test_prompt_uses_slot_and_verify_framing(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(workspace_id="ws-1", kind="letter", context={"title": "Doc"})
        prompt = llm.prompts[0].lower()
        assert "placeholder" in prompt
        assert "never invent" in prompt or "invent" in prompt


class TestNonPersistence:
    def test_use_case_depends_only_on_the_two_injected_ports(self):
        """Structural proof of the orphan-draft fix: the use case has no
        persistence dependency — only ``_retrieval`` and ``_llm``. It is
        impossible for it to create a WritingDraft row."""
        uc, _, _ = _use_case()
        # No writing/draft/repository/store attribute anywhere on the instance.
        attr_names = " ".join(vars(uc).keys()).lower()
        for forbidden in ("draft", "writing", "repo", "store", "persist"):
            assert forbidden not in attr_names


class _FakeDocumentRetrieval:
    """Captures the selection and returns fixed document chunks."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def search(self, *, workspace_id, query, file_ids, k=6):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "query": query,
                "file_ids": list(file_ids),
                "k": k,
            }
        )
        return list(self._chunks)


class TestSelectedDocumentGrounding:
    """Task #16 — author-selected uploaded documents lead the grounding set."""

    def _doc_chunk(self, content="Report shows 42 kids enrolled in Kampala."):
        return _Chunk(
            content=content,
            metadata={"section": "selected_document", "section_title": "Selected document — page 1", "pdf_id": "f-1"},
            score=0.9,
        )

    def test_selected_files_are_retrieved_and_lead_the_prompt(self):
        snapshot = _FakeRetrieval([_Chunk(content="Snapshot fact.")])
        docs = _FakeDocumentRetrieval([self._doc_chunk()])
        llm = _FakeLlm(json.dumps({"title": "T", "body_html": "<p>Body.</p>"}))
        uc = GenerateInteractiveDraftUseCase(retrieval_port=snapshot, llm_port=llm, document_retrieval_port=docs)
        result = uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={
                "title": "Q3 letter",
                "prompt": "thank the funder",
                "grounding_file_ids": ["f-1", "", None],
            },
        )
        # The document port got the sanitised selection.
        assert docs.calls and docs.calls[0]["file_ids"] == ["f-1"]
        assert docs.calls[0]["workspace_id"] == "ws-1"
        prompt = llm.prompts[0]
        # Doc chunk is present, labelled, and announced as primary.
        assert "Kampala" in prompt
        assert "Selected document" in prompt
        assert "ATTACHED specific documents" in prompt
        # Doc chunk leads the provenance list (prepended before snapshot).
        assert result["source_chunks"][0]["section"] == "selected_document"

    def test_document_chunks_join_the_faithfulness_grounding_set(self):
        docs = _FakeDocumentRetrieval([self._doc_chunk(content="We raised USD 4,321.87 this quarter.")])
        llm = _FakeLlm(json.dumps({"title": "T", "body_html": "<p>We raised USD 4,321.87.</p>"}))
        uc = GenerateInteractiveDraftUseCase(
            retrieval_port=_FakeRetrieval([]),
            llm_port=llm,
            document_retrieval_port=docs,
        )
        result = uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "report", "grounding_file_ids": ["f-1"]},
        )
        # The doc-sourced figure verifies as grounded.
        assert result["faithfulness"]["ok"] is True

    def test_no_selection_skips_document_retrieval(self):
        docs = _FakeDocumentRetrieval([self._doc_chunk()])
        uc = GenerateInteractiveDraftUseCase(
            retrieval_port=_FakeRetrieval([]),
            llm_port=_FakeLlm("{}"),
            document_retrieval_port=docs,
        )
        uc.execute(workspace_id="ws-1", kind="letter", context={"prompt": "x"})
        assert docs.calls == []

    def test_no_port_wired_is_harmless(self):
        uc, _, llm = _use_case(llm_content=json.dumps({"body_html": "<p>ok</p>"}))
        result = uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "x", "grounding_file_ids": ["f-1"]},
        )
        assert result["body_html"] == "<p>ok</p>"

    def test_document_retrieval_failure_degrades_to_snapshot_only(self):
        class _ExplodingDocs:
            def search(self, **kwargs):
                raise RuntimeError("store down")

        uc = GenerateInteractiveDraftUseCase(
            retrieval_port=_FakeRetrieval([_Chunk(content="Snapshot fact.")]),
            llm_port=_FakeLlm(json.dumps({"body_html": "<p>ok</p>"})),
            document_retrieval_port=_ExplodingDocs(),
        )
        result = uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "x", "grounding_file_ids": ["f-1"]},
        )
        assert result["body_html"] == "<p>ok</p>"
        assert len(result["source_chunks"]) == 1


class TestToneAndLength:
    """Task #17 — tone style steering + letter structure requirements."""

    def test_known_tone_expands_into_style_directives(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "thank them", "tone": "personal"},
        )
        prompt = llm.prompts[0]
        assert "TONE:" in prompt
        assert "first person singular" in prompt

    def test_emotional_tone_supported(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "share the story", "tone": "emotional"},
        )
        assert "Emotionally resonant" in llm.prompts[0]

    def test_unknown_tone_keeps_adjective_without_tone_block(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "x", "tone": "piratical"},
        )
        prompt = llm.prompts[0]
        assert "Draft a piratical letter" in prompt
        assert "TONE:" not in prompt

    def test_letter_task_requires_multiple_paragraphs(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(workspace_id="ws-1", kind="letter", context={"prompt": "x"})
        assert "two to three substantial paragraphs" in llm.prompts[0]
        assert "Never a single short paragraph" in llm.prompts[0]


class TestSocialKind:
    """Task #9 — social posts draft through the SAME grounded pipeline."""

    def test_social_task_is_hook_first_short_and_hashtagged(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="social",
            context={"prompt": "87 students enrolled this term"},
        )
        prompt = llm.prompts[0]
        assert "social media post" in prompt
        assert "hook" in prompt
        assert "hashtags" in prompt
        assert "never invented ones" in prompt

    def test_social_kind_grounds_like_every_other_kind(self):
        uc, retrieval, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="social",
            context={"prompt": "term wrap-up"},
        )
        # The retrieval port was consulted — unlike the agents chat tool,
        # the compose-flow social kind is grounded.
        assert retrieval.calls, "social kind must retrieve workspace context"


class TestTemplateScaffoldCompletion:
    """Task #17 — a template-seeded body is COMPLETED, not ignored."""

    _SCAFFOLD = "<p>Dear {{funder_name}},</p><p>Thank you for supporting [program name] this quarter.</p>"

    def test_scaffold_with_placeholders_is_injected_with_completion_rules(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "x", "existing_body_html": self._SCAFFOLD},
        )
        prompt = llm.prompts[0]
        assert "TEMPLATE SCAFFOLD" in prompt
        assert "{{funder_name}}" in prompt
        assert "NEVER invent one" in prompt

    def test_body_without_placeholders_is_not_injected(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={
                "prompt": "x",
                "existing_body_html": "<p>Fully written text already.</p>",
            },
        )
        assert "TEMPLATE SCAFFOLD" not in llm.prompts[0]

    def test_empty_body_is_not_injected(self):
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(workspace_id="ws-1", kind="letter", context={"prompt": "x"})
        assert "TEMPLATE SCAFFOLD" not in llm.prompts[0]

    def test_scaffold_is_capped(self):
        from components.agents.application.use_cases.generate_interactive_draft_use_case import (
            _MAX_SCAFFOLD_CHARS,
        )

        huge = "<p>{{token}}</p>" + ("x" * (_MAX_SCAFFOLD_CHARS * 2))
        uc, _, llm = _use_case(llm_content="{}")
        uc.execute(
            workspace_id="ws-1",
            kind="letter",
            context={"prompt": "x", "existing_body_html": huge},
        )
        # The prompt grew by at most the cap (plus instructions), not 2x it.
        assert len(llm.prompts[0]) < _MAX_SCAFFOLD_CHARS + 3000


class TestDesignedLayoutCompletion:
    """Task #19 — a layout-bearing draft is COMPLETED field-by-field."""

    def _layout(self):
        return {
            "version": 5,
            "blocks": [
                {"kind": "page_header", "payload": {"left": "Zaylan", "right": "Proposal"}},
                {"kind": "text", "payload": {"heading": "The need", "html": "<p>Placeholder.</p>"}},
                {
                    "kind": "numbered_sections",
                    "payload": {"sections": [{"title": "Plan", "body_html": "<p>Fill me.</p>"}]},
                },
                {"kind": "stat_row", "payload": {"stats": [{"value": "[amount]", "label": "Ask"}]}},
            ],
        }

    def _run(self, *, llm_json, chunks=None):
        retrieval = _FakeRetrieval(chunks or [])
        llm = _FakeLlm(llm_json)
        uc = GenerateInteractiveDraftUseCase(retrieval_port=retrieval, llm_port=llm)
        result = uc.execute(
            workspace_id="ws-1",
            kind="proposal",
            context={"prompt": "pitch", "existing_layout": self._layout()},
        )
        return result, llm

    def test_fields_are_offered_and_contract_switches(self):
        _, llm = self._run(llm_json="{}")
        prompt = llm.prompts[0]
        assert "DESIGNED DOCUMENT" in prompt
        assert "[b1.html]" in prompt
        assert "[b2.sections.0.body_html]" in prompt
        assert "[b3.stats.0.value]" in prompt
        # Chrome fields are NOT offered.
        assert "b0.left" not in prompt
        # Layout contract replaces the kind contract.
        assert '"fields"' in prompt

    def test_completions_apply_and_layout_returned(self):
        result, _ = self._run(
            llm_json=json.dumps(
                {
                    "title": "Mwanza expansion",
                    "fields": {
                        "b1.html": "<p>87 students need a second room.</p>",
                        "b2.sections.0.body_html": "<p>Hire two tutors.</p>",
                        "b3.stats.0.value": "$5,432",
                    },
                }
            ),
            chunks=[_Chunk(content="87 students enrolled; spend was $5,432.")],
        )
        layout = result["layout"]
        assert layout["blocks"][1]["payload"]["html"] == "<p>87 students need a second room.</p>"
        assert layout["blocks"][2]["payload"]["sections"][0]["body_html"] == "<p>Hire two tutors.</p>"
        assert layout["blocks"][3]["payload"]["stats"][0]["value"] == "$5,432"
        # Applied texts feed faithfulness — grounded figures verify.
        assert result["faithfulness"]["ok"] is True
        # Untouched fields keep their copy.
        assert layout["blocks"][2]["payload"]["sections"][0]["title"] == "Plan"

    def test_malformed_field_ids_never_corrupt_the_layout(self):
        result, _ = self._run(
            llm_json=json.dumps(
                {
                    "fields": {
                        "b99.html": "<p>x</p>",
                        "b0.left": "hacked",
                        "b2.sections.9.body_html": "<p>x</p>",
                        "not-a-path": "<p>x</p>",
                        "b1.html": 42,
                    }
                }
            )
        )
        layout = result["layout"]
        assert layout["blocks"][0]["payload"]["left"] == "Zaylan"
        assert layout["blocks"][1]["payload"]["html"] == "<p>Placeholder.</p>"

    def test_no_layout_keeps_classic_body_path(self):
        uc, _, llm = _use_case(llm_content=json.dumps({"body_html": "<p>classic</p>"}))
        result = uc.execute(workspace_id="ws-1", kind="letter", context={"prompt": "x"})
        assert result["body_html"] == "<p>classic</p>"
        assert "layout" not in result


class TestVerbatimQuoteGuard:
    """Task #19 — quote completions must be verbatim-backed by grounding."""

    def _layout(self):
        return {
            "version": 5,
            "blocks": [
                {
                    "kind": "block_quote",
                    "payload": {
                        "quote_html": "<p>Replace this with a real quote.</p>",
                        "attribution": "Their name",
                        "role": "",
                    },
                }
            ],
        }

    def _run(self, *, quote, chunks):
        llm = _FakeLlm(
            json.dumps(
                {
                    "fields": {
                        "b0.quote_html": quote,
                        "b0.attribution": "Amina N.",
                    }
                }
            )
        )
        uc = GenerateInteractiveDraftUseCase(retrieval_port=_FakeRetrieval(chunks), llm_port=llm)
        return uc.execute(
            workspace_id="ws-1",
            kind="proposal",
            context={"prompt": "pitch", "existing_layout": self._layout()},
        )

    def test_verbatim_quote_is_applied(self):
        result = self._run(
            quote="<p>My son reads to me every evening now.</p>",
            chunks=[_Chunk(content='A parent said: "My son reads to me every evening now."')],
        )
        payload = result["layout"]["blocks"][0]["payload"]
        assert payload["quote_html"] == "<p>My son reads to me every evening now.</p>"
        assert payload["attribution"] == "Amina N."

    def test_paraphrased_quote_is_reverted_with_its_attribution(self):
        result = self._run(
            quote="<p>My daughter's confidence has soared since joining.</p>",
            chunks=[_Chunk(content='A parent said: "My son reads to me every evening now."')],
        )
        payload = result["layout"]["blocks"][0]["payload"]
        # The invented quote AND its attribution keep the template copy.
        assert payload["quote_html"] == "<p>Replace this with a real quote.</p>"
        assert payload["attribution"] == "Their name"
