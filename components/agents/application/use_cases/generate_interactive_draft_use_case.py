"""Grounded, non-persisting interactive draft generation (SEE-169).

This is the application-layer use case behind the editor's "Ask AI" path
(``components/content/api/ai_draft_controller.py`` →
``LangchainWritingAiAdapter.draft_for_kind``). It exists to fix the
orphan-draft bug *structurally*: the editor path generates body text for
the document the user already has open and returns it, **without ever
persisting a WritingDraft row**. The persisting ``writing_agent`` tools
(``infrastructure/adapters/langchain/tools/writing_agent.py``) stay
untouched — they serve the chat-orchestrator surface, where self-persist
+ "Open in Writing →" is the intended behaviour.

Grounding (the moat — see ``docs/plans/GROUNDED_CONTENT_GENERATION_2026-06-27.md``):

1. Retrieve workspace RAG context via the KNOWLEDGE workspace-retrieval
   application port (the same ``WorkspaceRetrievalPort`` the deep-run
   planner prefetch uses), seeded with the document title + kind +
   prompt.
2. Build a kind-appropriate, document-aware prompt that injects the
   retrieved chunks as grounding ("ground every fact in the provided
   context; do not invent numbers or names") plus the document's own
   title / recipient / topic / prompt.
3. Generate via the KNOWLEDGE LLM application port (``LlmPort``) — the
   same port the rest of the AI stack uses. No ``LLMFactory`` / ``import
   openai`` in the application layer.

Layer rules: this module imports NO Django, NO DRF, NO ORM, NO
infrastructure. Ports are injected by ``AIProvider`` (the agents
composition root). Cross-context *application* imports (knowledge ports)
are allowed by the architecture manifesto; cross-context infrastructure
imports are not.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from components.agents.domain.services.faithfulness_verifier import (
    FaithfulnessVerifier,
)

logger = logging.getLogger(__name__)


AGENT_TYPE = "writing_agent"

# Default number of grounding chunks to retrieve. Mirrors the planner
# prefetch default (k=5) with one extra to widen recall for document-aware
# drafting.
_DEFAULT_RETRIEVAL_K = 6

# Maximum characters of a single chunk to inline into the prompt — keeps
# the grounding block bounded so a few large chunks can't blow the token
# budget.
_MAX_CHUNK_CHARS = 1200

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

# Cap on the template-scaffold snippet inlined into the prompt (task #17) —
# scaffolds are short by nature; the cap only guards a pathological body.
_MAX_SCAFFOLD_CHARS = 4000


# ── kind → task framing ───────────────────────────────────────────────────
# Each entry frames the writing task for one document kind. The grounding
# block + output contract are appended uniformly below.
#
# Length matters (task #17 — Henry: "just one paragraph? for a LETTER?"):
# the prose kinds carry an explicit structure/length requirement, because
# without one the model reliably returns a single thin paragraph.
_LETTER_STRUCTURE = (
    " Write two to three substantial paragraphs — a warm opening that names "
    "the recipient and the reason for writing, a body grounded in concrete "
    "specifics (what happened, what it made possible), and a closing that "
    "looks ahead and thanks them. Never a single short paragraph."
)

_KIND_TASKS: dict[str, str] = {
    "letter": "Draft a {tone} letter to {recipient}." + _LETTER_STRUCTURE,
    "update": "Draft a {tone} update note for {recipient}." + _LETTER_STRUCTURE,
    # Auto-Sec: "memo" is the security-report kind the Reports studio creates.
    # Structured document voice — NEVER a letter: no salutation ("Dear …"),
    # no sign-off, no first-person pleasantries.
    "memo": (
        "Write a {tone} SECURITY REPORT (not a letter — no salutation, no "
        "sign-off, no 'Dear team'). Use bolded section headings: Summary, "
        "Timeline, Impact, Containment / Remediation, and Next Steps. Be "
        "factual and specific; state only what the prompt and grounding "
        "support, and mark unknowns as 'undetermined' rather than guessing."
    ),
    "summary": (
        "Write a concise {tone} security posture summary for the period "
        "{period}. Document voice with headings — no salutation or sign-off."
    ),
    "proposal": (
        "Draft a {tone} project proposal about {topic}. Structure it as a "
        "funder-ready pitch: the need (grounded in real context), what you "
        "will do (concrete activities), what it will achieve (outcomes), "
        "and what you are asking for. At least four substantial sections — "
        "never a single paragraph."
    ),
    "blog": "Draft a {tone}, public-facing, story-first blog post about {topic}.",
    "social": (
        "Draft a {tone} social media post about {topic}. Open with a hook "
        "line that stops the scroll, then two to five short sentences "
        "grounded in concrete specifics — real numbers and real moments "
        "from the grounding only, never invented ones. Close with a simple "
        "call to action, then three to five relevant hashtags on the final "
        "line. Write it ready to paste into LinkedIn, Instagram, or "
        "Facebook: plain sentences, no headings, no markdown."
    ),
    "newsletter": "Draft a {tone} supporter newsletter covering the period {period}.",
    "recipient_update": "Draft a {tone} update about the recipient/beneficiary named '{entity}'." + _LETTER_STRUCTURE,
    "project_update": "Draft a {tone} update about the project named '{entity}'." + _LETTER_STRUCTURE,
    "event_update": "Draft a {tone} update about the event named '{entity}'." + _LETTER_STRUCTURE,
    "campaign_update": "Draft a {tone} update about the fundraising campaign named '{entity}'." + _LETTER_STRUCTURE,
}

_DEFAULT_TASK = "Write a {tone} security operations document. Document voice — no salutation or sign-off."

# ── tone → style directives (task #17) ─────────────────────────────────────
# A bare adjective in the task line ("Draft a warm letter") is weak steering.
# Each tone expands into explicit style directives injected as a TONE block.
# Unknown tones fall back to the adjective alone — the vocabulary is open.
_TONE_STYLES: dict[str, str] = {
    "warm": ("Warm and generous: gratitude up front, people before numbers, sincere without being saccharine."),
    "formal": (
        "Formal and polished: complete sentences, no contractions, "
        "professional register suitable for a board or an institutional funder."
    ),
    "concise": (
        "Concise: short sentences, no throat-clearing, every sentence earns "
        "its place. Prefer one strong specific over three vague ones."
    ),
    "energetic": (
        "Energetic and upbeat: momentum verbs, celebrate wins, keep the "
        "reader moving — without exclamation-mark overload."
    ),
    "conversational": (
        "Conversational: write like a trusted colleague speaking — contractions welcome, plain words, first person."
    ),
    "personal": (
        "Personal and intimate: first person singular, address the reader "
        "directly by name, reference the specific relationship and history "
        "you share — this reads like a note from one person to another, "
        "never a broadcast."
    ),
    "emotional": (
        "Emotionally resonant: lead with a human moment, let the stakes and "
        "feelings show, name the impact on real people — heartfelt and "
        "honest, never manipulative or exaggerated."
    ),
}


class GenerateInteractiveDraftUseCase:
    """Generate grounded body text for an open document — never persists.

    Args:
        retrieval_port: a ``WorkspaceRetrievalPort`` — ``.search(
            workspace_id, query, k)`` returns ranked chunks (duck-typed:
            each has ``.content``, ``.metadata``, ``.score``).
        llm_port: an ``LlmPort`` — ``.invoke(prompt)`` returns a response
            with a ``.content`` string.
        fact_sheet_port: an optional ``EntityFactSheetPort`` (SEE-170) —
            ``.fact_sheet(workspace_id, entity_type, entity_id)`` returns a
            compact dict of a linked entity's real data. ``None`` disables
            per-entity grounding (the use case still works, just less
            grounded for entity-update kinds).
        voice_profile_port: an optional voice-profile reader (SEE-172) —
            duck-typed ``.style_card(workspace_id) -> str`` returns the
            workspace's brand voice as a prompt style-card block (the content
            side owns it; we only receive the rendered string). ``None`` (or
            an empty profile) disables voice steering — the draft is still
            grounded, just in the default house voice. Voice is injected
            SEPARATELY from grounding and is never added to the faithfulness
            set.
        retrieval_k: how many grounding chunks to request.
    """

    def __init__(
        self,
        *,
        retrieval_port: Any,
        llm_port: Any,
        fact_sheet_port: Any | None = None,
        voice_profile_port: Any | None = None,
        document_retrieval_port: Any | None = None,
        retrieval_k: int = _DEFAULT_RETRIEVAL_K,
    ) -> None:
        self._retrieval = retrieval_port
        self._llm = llm_port
        self._fact_sheet = fact_sheet_port
        self._voice = voice_profile_port
        self._documents = document_retrieval_port
        self._k = retrieval_k
        self._verifier = FaithfulnessVerifier()

    def execute(
        self,
        *,
        workspace_id: str,
        kind: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return ``{title, body_html, excerpt, sections, source_chunks,
        faithfulness, agent_type}``. Never raises for an empty/failed
        retrieval — it just produces less-grounded copy. NEVER persists
        anything.

        ``faithfulness`` (SEE-171) is the slot-and-verify report:
        ``{ok, unsupported_numbers, unsupported_names, checked}`` — every
        money/quantity/date in the generated body checked against the
        grounding set (RAG chunks + linked-entity facts). It is surfaced,
        never silently stripped, so the editor can flag unverified figures.
        """

        ctx = dict(context or {})
        title = (ctx.get("title") or "").strip()
        prompt_text = (ctx.get("prompt") or "").strip()
        topic = (ctx.get("topic") or "").strip()
        recipient = (ctx.get("recipient_name") or "").strip()

        seed_query = self._build_seed_query(
            title=title, kind=kind, prompt=prompt_text, topic=topic, recipient=recipient
        )
        chunks = self._retrieve(workspace_id=workspace_id, query=seed_query)

        # Author-SELECTED documents (task #16): when the editor supplies
        # grounding_file_ids, retrieve from those files DIRECTLY (the
        # uploaded-documents store) instead of hoping the workspace-wide
        # ranking surfaces them. Doc chunks lead the grounding set — the
        # author picked them for this draft, so they are the primary
        # source, with the workspace snapshot as supporting context.
        doc_chunks = self._retrieve_documents(
            workspace_id=workspace_id,
            query=seed_query,
            file_ids=ctx.get("grounding_file_ids") or [],
        )
        if doc_chunks:
            chunks = doc_chunks + chunks

        # SEE-170: structured facts for the linked entity, if any.
        fact_sheet = self._fetch_fact_sheet(workspace_id=workspace_id, kind=kind, ctx=ctx)

        # SEE-172: per-workspace brand voice, rendered as a style card.
        # STEERS the copy; never grounding (kept out of grounding_texts).
        voice_card = self._fetch_voice_card(workspace_id=workspace_id)

        prompt = self._build_prompt(
            kind=kind,
            ctx=ctx,
            chunks=chunks,
            fact_sheet=fact_sheet,
            voice_card=voice_card,
        )

        generated = self._generate(prompt, workspace_id=workspace_id, kind=kind)

        # DESIGNED documents (task #19): when the draft carries a block
        # layout, the model returns per-field completions — apply them to a
        # copy of the layout and verify THOSE texts. Otherwise the classic
        # body_html path.
        # SEE-171: the grounding set feeds both the faithfulness check and
        # the verbatim-quote guard on designed-layout completions.
        grounding_texts = self._grounding_texts(chunks=chunks, fact_sheet=fact_sheet)

        layout = ctx.get("existing_layout")
        completed_layout = None
        if isinstance(layout, dict) and layout.get("blocks"):
            fields = generated.get("fields") if isinstance(generated.get("fields"), dict) else {}
            completed_layout, applied_texts = self._apply_layout_fields(layout, fields, grounding_texts=grounding_texts)
            body_html = "\n".join(applied_texts)
        else:
            body_html = generated.get("body_html") or generated.get("content_html") or ""

        report = self._verifier.verify(generated_html=body_html, grounding_texts=grounding_texts)

        result = {
            "title": generated.get("title") or title or "",
            "body_html": body_html,
            "excerpt": generated.get("excerpt") or "",
            "sections": generated.get("sections") or [],
            "source_chunks": [self._serialise_chunk(c) for c in chunks],
            "faithfulness": report.as_dict(),
            "agent_type": AGENT_TYPE,
        }
        if completed_layout is not None:
            result["layout"] = completed_layout
        logger.info(
            "interactive_draft.generated workspace_id=%s kind=%s chunks=%s "
            "fact_sheet=%s has_body=%s faithful=%s unverified_numbers=%s",
            workspace_id,
            kind,
            len(chunks),
            bool(fact_sheet),
            bool(result["body_html"]),
            report.ok,
            len(report.unsupported_numbers),
        )
        return result

    # ── per-entity fact sheet (SEE-170) ────────────────────────────────

    def _fetch_fact_sheet(self, *, workspace_id: str, kind: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Best-effort structured facts for the linked entity. Returns
        ``{}`` when no port is wired, no entity is linked, or the lookup
        fails — entity grounding is enrichment, never a hard dependency."""
        if not self._fact_sheet:
            return {}
        entity_id = (ctx.get("related_entity_id") or "").strip()
        if not workspace_id or not entity_id:
            return {}
        entity_type = (ctx.get("related_entity_type") or "").strip()
        if not entity_type:
            entity_type = self._infer_entity_type(kind)
        if not entity_type:
            return {}
        try:
            sheet = self._fact_sheet.fact_sheet(
                workspace_id=str(workspace_id),
                entity_type=entity_type,
                entity_id=entity_id,
            )
        except Exception:
            logger.exception(
                "interactive_draft.fact_sheet_failed workspace_id=%s entity_type=%s",
                workspace_id,
                entity_type,
            )
            return {}
        return sheet or {}

    # ── per-workspace voice (SEE-172) ──────────────────────────────────

    def _fetch_voice_card(self, *, workspace_id: str) -> str:
        """Best-effort brand-voice style card. Returns ``""`` when no port
        is wired, no profile exists, or the lookup fails — voice steering is
        enrichment, never a hard dependency."""
        if not self._voice or not workspace_id:
            return ""
        try:
            return self._voice.style_card(workspace_id=str(workspace_id)) or ""
        except Exception:
            logger.exception("interactive_draft.voice_card_failed workspace_id=%s", workspace_id)
            return ""

    @staticmethod
    def _infer_entity_type(kind: str) -> str:
        mapping = {
            "recipient_update": "recipient",
            "project_update": "project",
            "event_update": "event",
            "campaign_update": "campaign",
        }
        return mapping.get(kind, "")

    @staticmethod
    def _grounding_texts(*, chunks: list[Any], fact_sheet: dict[str, Any]) -> list[str]:
        texts = [(getattr(c, "content", "") or "") for c in chunks]
        facts = fact_sheet.get("facts") or []
        if facts:
            texts.append("\n".join(str(f) for f in facts))
        return texts

    # ── retrieval ──────────────────────────────────────────────────────

    def _retrieve(self, *, workspace_id: str, query: str) -> list[Any]:
        if not workspace_id or not query:
            return []
        try:
            chunks = self._retrieval.search(workspace_id=str(workspace_id), query=query, k=self._k)
        except Exception:
            logger.exception("interactive_draft.retrieval_failed workspace_id=%s", workspace_id)
            return []
        return list(chunks or [])

    def _retrieve_documents(self, *, workspace_id: str, query: str, file_ids: list[Any]) -> list[Any]:
        """Chunks from the author's SELECTED uploaded documents.

        No port wired / no selection / failure ⇒ ``[]`` — document
        grounding is targeted enrichment, never a hard dependency. The
        adapter pins results to the workspace, so foreign file ids match
        nothing (tenancy by construction).
        """
        clean_ids = [str(i) for i in (file_ids or []) if i]
        if not self._documents or not workspace_id or not query or not clean_ids:
            return []
        try:
            chunks = self._documents.search(
                workspace_id=str(workspace_id),
                query=query,
                file_ids=clean_ids,
                k=self._k,
            )
        except Exception:
            logger.exception(
                "interactive_draft.document_retrieval_failed workspace_id=%s file_ids=%s",
                workspace_id,
                clean_ids,
            )
            return []
        return list(chunks or [])

    @staticmethod
    def _build_seed_query(*, title: str, kind: str, prompt: str, topic: str, recipient: str) -> str:
        parts = [p for p in (title, kind.replace("_", " "), prompt, topic, recipient) if p]
        return " ".join(parts).strip()

    @staticmethod
    def _serialise_chunk(chunk: Any) -> dict[str, Any]:
        metadata = getattr(chunk, "metadata", None) or {}
        score = getattr(chunk, "score", 0.0) or 0.0
        return {
            "section": metadata.get("section") or "",
            "section_title": metadata.get("section_title") or metadata.get("title") or "",
            "content": (getattr(chunk, "content", "") or "").strip(),
            "score": round(float(score), 4) if score else 0.0,
        }

    # ── prompt building ────────────────────────────────────────────────

    @staticmethod
    def _conversation_block(conversation: Any) -> str:
        """Chat continuity (task #31): earlier assist-session turns, so a
        follow-up like "now make the opening warmer" keeps its meaning.
        The document context above already reflects those turns — the
        model must build on them, not undo them. User-authored text at
        the same trust level as the prompt; the controller caps turns
        and length."""
        if not isinstance(conversation, list) or not conversation:
            return ""
        lines = []
        for turn in conversation:
            if not isinstance(turn, dict):
                continue
            role = "You" if turn.get("role") == "assistant" else "Author"
            text = str(turn.get("text") or "").strip()
            if text:
                lines.append(f"- {role}: {text}")
        if not lines:
            return ""
        return (
            "EARLIER IN THIS ASSIST SESSION (already applied to the document "
            "above — build on these, do not undo them unless asked):\n" + "\n".join(lines) + "\n\n"
        )

    def _build_prompt(
        self,
        *,
        kind: str,
        ctx: dict[str, Any],
        chunks: list[Any],
        fact_sheet: dict[str, Any] | None = None,
        voice_card: str = "",
    ) -> str:
        tone = (ctx.get("tone") or "warm").strip() or "warm"
        recipient = (ctx.get("recipient_name") or "the recipient").strip() or "the recipient"
        topic = (ctx.get("topic") or ctx.get("prompt") or "the organization's work").strip()
        entity = (ctx.get("recipient_name") or ctx.get("title") or "this record").strip()
        period = self._format_period(ctx.get("period_start"), ctx.get("period_end"))
        title = (ctx.get("title") or "").strip()
        author_intent = (ctx.get("prompt") or "").strip()

        task = _KIND_TASKS.get(kind, _DEFAULT_TASK).format(
            tone=tone, recipient=recipient, topic=topic, entity=entity, period=period
        )

        # Task #17: a bare adjective is weak steering — expand known tones
        # into explicit style directives. Unknown tones keep the adjective.
        tone_style = _TONE_STYLES.get(tone.lower(), "")
        tone_block = f"TONE: {tone_style}\n\n" if tone_style else ""

        grounding_block = self._grounding_block(chunks)
        document_block = self._document_block(title=title, author_intent=author_intent, ctx=ctx)
        # Designed documents (task #19): the layout's fillable fields replace
        # the body-scaffold path AND the kind output contract — the model
        # completes the design instead of writing a free-form body.
        layout = ctx.get("existing_layout")
        layout_fields = self._extract_layout_fields(layout) if isinstance(layout, dict) and layout.get("blocks") else []
        scaffold_block = "" if layout_fields else self._scaffold_block(ctx.get("existing_body_html") or "")
        layout_block = self._layout_fields_block(layout_fields)
        fact_sheet_block = self._fact_sheet_block(fact_sheet)
        # SEE-172: voice block sits between the document context and the
        # facts. It is STYLE only — deliberately NOT part of grounding_texts,
        # so the faithfulness verifier never treats voice/exemplars as facts.
        voice_block = f"{voice_card}\n" if (voice_card or "").strip() else ""
        conversation_block = self._conversation_block(ctx.get("conversation"))

        return (
            "You are the Writing Assistant for a small nonprofit's operations "
            "platform. Write warm, plain-spoken, concrete copy — never fluff, "
            "never marketing-ese.\n\n"
            f"TASK: {task}\n\n"
            f"{tone_block}"
            f"{document_block}\n"
            f"{conversation_block}"
            f"{scaffold_block}"
            f"{layout_block}"
            f"{voice_block}"
            f"{fact_sheet_block}"
            f"{grounding_block}\n"
            "GROUNDING RULES (slot-and-verify — mandatory):\n"
            "- Only state monetary amounts, counts, dates, and proper names "
            "that appear in the LINKED RECORD or WORKSPACE CONTEXT above. "
            "Treat those figures as the only verified facts you have.\n"
            "- If a needed figure, amount, date, or name is NOT in the "
            "context, write around it or leave a [bracketed placeholder] for "
            "the author to fill — NEVER invent or estimate it.\n"
            "- Every figure you write will be checked against the context "
            "above; an invented number is a trust failure.\n"
            "- Stay focused on this specific document's subject and intent; do "
            "not drift to a generic 'top donor' style template.\n\n"
            f"{self._layout_output_contract() if layout_fields else self._output_contract(kind)}"
        )

    # ── designed-document field completion (task #19) ───────────────────

    # Per block kind: which payload text fields the model may complete.
    # Chrome blocks (page_header, cta, footer, hero images) keep their
    # design identity and are never rewritten.
    _LAYOUT_FILLABLE: dict[str, tuple[str, ...]] = {
        "text": ("heading", "html"),
        # title + accent_word joined the fillable set for the blank-draft
        # design path (task #19): a template's "Your headline goes / here."
        # is placeholder CONTENT, not chrome — leaving it produced designed
        # drafts with placeholder headlines. accent_word is the highlighted
        # final word of the title (the prompt explains the pairing).
        "display_heading": ("title", "accent_word", "subtitle"),
        "image_text_card": ("title", "body_html"),
        "block_quote": ("quote_html", "attribution", "role"),
        # poster_hero (v6): the magazine-cover headline is content; the
        # image + eyebrows are chrome. team_grid is deliberately ABSENT —
        # its members are real humans the AI must never invent.
        "poster_hero": ("headline", "accent_word", "note_left", "note_right"),
    }
    # Nested collections: (payload key, entry fields).
    _LAYOUT_FILLABLE_NESTED: dict[str, tuple[str, tuple[str, ...]]] = {
        "numbered_sections": ("sections", ("body_html",)),
        "stat_row": ("stats", ("value",)),
    }

    @classmethod
    def _extract_layout_fields(cls, layout: dict[str, Any]) -> list[dict[str, str]]:
        """Flatten a block layout's completable text fields into
        ``[{id, kind, current}]``. Field ids are stable paths
        (``b2.html``, ``b4.sections.1.body_html``) that
        ``_apply_layout_fields`` re-resolves."""
        fields: list[dict[str, str]] = []
        for index, block in enumerate(layout.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            kind = block.get("kind") or ""
            payload = block.get("payload")
            if not isinstance(payload, dict):
                continue
            for key in cls._LAYOUT_FILLABLE.get(kind, ()):
                value = payload.get(key)
                if isinstance(value, str):
                    fields.append({"id": f"b{index}.{key}", "kind": kind, "current": value})
            nested = cls._LAYOUT_FILLABLE_NESTED.get(kind)
            if nested:
                collection_key, entry_fields = nested
                for entry_index, entry in enumerate(payload.get(collection_key) or []):
                    if not isinstance(entry, dict):
                        continue
                    for key in entry_fields:
                        value = entry.get(key)
                        if isinstance(value, str):
                            fields.append(
                                {
                                    "id": f"b{index}.{collection_key}.{entry_index}.{key}",
                                    "kind": kind,
                                    "current": value,
                                }
                            )
        return fields

    @staticmethod
    def _layout_fields_block(fields: list[dict[str, str]]) -> str:
        """Render the designed document's completable fields for the prompt."""
        if not fields:
            return ""
        lines = [
            "DESIGNED DOCUMENT (complete it — do NOT restructure):",
            "The document is a designed block layout. Below are its editable",
            "text fields (most hold instructional placeholder copy). Replace",
            "the instructional copy with real, grounded content; keep the",
            "design's structure and voice. Special rules:",
            "- stat_row values: use ONLY figures present in the context; keep",
            "  the existing placeholder when the figure is not available.",
            "- block_quote: fill ONLY with a VERBATIM quote from a real person",
            "  found in the context; otherwise keep the instructional copy.",
            "- html/body_html fields take simple HTML (<p>, <strong>, <ul>).",
            "- display_heading title + accent_word form ONE headline: title is",
            "  the opening words, accent_word the short highlighted ending",
            "  (1-2 words). ALWAYS replace both when they hold placeholder",
            "  copy like 'Your headline goes' / 'here.'.",
            "FIELDS:",
        ]
        for field in fields:
            current = field["current"][:400]
            lines.append(f"[{field['id']}] ({field['kind']}) currently: {current}")
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _normalise_text(value: str) -> str:
        """Strip tags + collapse whitespace + casefold, for verbatim checks."""
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = re.sub(r"[\s\u00a0]+", " ", text).strip().casefold()
        # Normalise curly quotes/apostrophes so smart-quote drift doesn't
        # fail a genuinely verbatim quote.
        return text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')

    @staticmethod
    def _layout_output_contract() -> str:
        return (
            "Return ONLY valid JSON (no markdown fences, no commentary):\n"
            "{\n"
            '  "title": str — short document headline,\n'
            '  "fields": { "<field id>": "<new content>", ... } — ONLY the\n'
            "  fields you are completing; omit a field to keep it as-is\n"
            "}\n"
        )

    @classmethod
    def _apply_layout_fields(
        cls,
        layout: dict[str, Any],
        fields: dict[str, Any],
        grounding_texts: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Deep-copy the layout and apply the model's per-field completions.

        Unknown/malformed field ids and non-string values are ignored — a
        confused completion can never corrupt the layout's structure.

        VERBATIM-QUOTE GUARD: a ``block_quote`` ``quote_html`` completion is
        applied ONLY when its text actually appears in the grounding set —
        the prompt's verbatim-only rule is advisory to the model, this check
        is deterministic. A paraphrased/invented quote silently keeps the
        template's instructional copy instead (caught live 2026-07-13: the
        model paraphrased "My son reads to me every evening now" into a
        different sentence). Attribution/role ride the same acceptance.

        Returns ``(completed_layout, applied_texts)`` — the applied texts
        feed the faithfulness verifier.
        """
        import copy

        grounding_blob = cls._normalise_text(" ".join(grounding_texts or []))

        completed = copy.deepcopy(layout)
        blocks = completed.get("blocks") or []
        applied: list[str] = []
        rejected_quote_blocks: set[int] = set()
        # Pass 1: decide which block_quote completions are verbatim-backed.
        for raw_id, value in (fields or {}).items():
            if not (isinstance(raw_id, str) and isinstance(value, str)):
                continue
            parts = raw_id.split(".")
            if len(parts) == 2 and parts[1] == "quote_html" and parts[0].startswith("b"):
                try:
                    block_index = int(parts[0][1:])
                    kind = (blocks[block_index] or {}).get("kind")
                except (ValueError, IndexError, TypeError):
                    continue
                if kind != "block_quote":
                    continue
                quote_text = cls._normalise_text(value)
                if not quote_text or quote_text not in grounding_blob:
                    rejected_quote_blocks.add(block_index)

        for raw_id, value in (fields or {}).items():
            if not isinstance(value, str) or not isinstance(raw_id, str):
                continue
            # The whole quote block's completion stands or falls with the
            # verbatim check — a rejected quote keeps its attribution too.
            head = raw_id.split(".")[0]
            if head.startswith("b") and head[1:].isdigit() and int(head[1:]) in rejected_quote_blocks:
                continue
            parts = raw_id.split(".")
            if not parts or not parts[0].startswith("b"):
                continue
            try:
                block_index = int(parts[0][1:])
                block = blocks[block_index]
                payload = block.get("payload")
                kind = block.get("kind") or ""
                if not isinstance(payload, dict):
                    continue
                if len(parts) == 2:
                    key = parts[1]
                    if key not in cls._LAYOUT_FILLABLE.get(kind, ()):
                        continue
                    payload[key] = value
                elif len(parts) == 4:
                    collection_key, entry_index, key = parts[1], int(parts[2]), parts[3]
                    nested = cls._LAYOUT_FILLABLE_NESTED.get(kind)
                    if not nested or nested[0] != collection_key or key not in nested[1]:
                        continue
                    entry = (payload.get(collection_key) or [])[entry_index]
                    if not isinstance(entry, dict):
                        continue
                    entry[key] = value
                else:
                    continue
                applied.append(value)
            except (ValueError, IndexError, KeyError, TypeError):
                continue
        return completed, applied

    @staticmethod
    def _fact_sheet_block(fact_sheet: dict[str, Any] | None) -> str:
        """Render the linked entity's real data as verified grounding
        (SEE-170). Empty string when no entity is linked."""
        if not fact_sheet:
            return ""
        facts = fact_sheet.get("facts") or []
        if not facts:
            return ""
        name = (fact_sheet.get("name") or "").strip()
        entity_type = (fact_sheet.get("entity_type") or "record").strip()
        header = f"LINKED RECORD ({entity_type}"
        header += f": {name}" if name else ""
        header += ") — real data, ground entity facts in this:"
        lines = [header]
        lines.extend(f"- {fact}" for fact in facts)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_period(start: Any, end: Any) -> str:
        start_s = str(start) if start else ""
        end_s = str(end) if end else ""
        if start_s and end_s:
            return f"{start_s} to {end_s}"
        return start_s or end_s or "the recent period"

    @staticmethod
    def _document_block(*, title: str, author_intent: str, ctx: dict[str, Any]) -> str:
        lines = ["DOCUMENT CONTEXT:"]
        if title:
            lines.append(f"- Document title: {title}")
        if author_intent:
            lines.append(f"- Author intent / prompt: {author_intent}")
        related_type = (ctx.get("related_entity_type") or "").strip()
        if related_type:
            lines.append(f"- Linked record type: {related_type}")
        if len(lines) == 1:
            lines.append("- (no extra document metadata supplied)")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _scaffold_block(existing_body_html: str) -> str:
        """The open document's current body, when it is a template scaffold.

        Task #17: drafts composed from a template start as a scaffold full
        of ``{{tokens}}`` / ``[bracketed placeholders]`` — but the AI never
        SAW the document, so it could not complete it. When the body
        contains placeholders, inject it with completion instructions:
        keep the structure, fill each placeholder from the request fields
        or the grounding context, keep a [bracketed placeholder] ONLY when
        the value is genuinely unavailable — never invent one.

        A body without placeholders is not injected: the editor's Generate
        flow appends to it, so echoing it back only invites duplication.
        """
        body = (existing_body_html or "").strip()
        if not body:
            return ""
        has_placeholders = bool(re.search(r"\{\{[^}]+\}\}", body) or re.search(r"\[[^\]\n]{2,60}\]", body))
        if not has_placeholders:
            return ""
        snippet = body[:_MAX_SCAFFOLD_CHARS]
        return (
            "TEMPLATE SCAFFOLD (the document's current body — COMPLETE it):\n"
            "The author started from a template. Produce the finished "
            "document: keep its structure, sections, and voice; replace "
            "every {{token}} and [bracketed placeholder] with the correct "
            "value from the recipient field, the LINKED RECORD, or the "
            "WORKSPACE CONTEXT below. If a value is genuinely not available "
            "anywhere, keep a [bracketed placeholder] for the author — "
            "NEVER invent one.\n"
            f"{snippet}\n"
        )

    def _grounding_block(self, chunks: list[Any]) -> str:
        if not chunks:
            return "WORKSPACE CONTEXT (retrieved): none found. Be honest and general; do not invent specifics.\n"
        has_selected_docs = any(
            (getattr(c, "metadata", None) or {}).get("section") == "selected_document" for c in chunks
        )
        lines = ["WORKSPACE CONTEXT (retrieved — ground facts in this):"]
        if has_selected_docs:
            lines.insert(
                0,
                "The author ATTACHED specific documents for this draft — the "
                "'Selected document' chunks below are the PRIMARY source; use "
                "their facts and figures first.",
            )
        for idx, chunk in enumerate(chunks, start=1):
            content = (getattr(chunk, "content", "") or "").strip()
            if not content:
                continue
            snippet = content[:_MAX_CHUNK_CHARS]
            metadata = getattr(chunk, "metadata", None) or {}
            label = metadata.get("section_title") or metadata.get("section") or ""
            header = f"[{idx}] {label}".rstrip()
            lines.append(f"{header}\n{snippet}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _output_contract(kind: str) -> str:
        if kind == "blog":
            return (
                "Return ONLY valid JSON (no markdown fences, no commentary):\n"
                "{\n"
                '  "title": str,\n'
                '  "excerpt": str — 1-2 sentence teaser,\n'
                '  "body_html": str — full post HTML\n'
                "}\n"
            )
        if kind == "newsletter":
            return (
                "Return ONLY valid JSON (no markdown fences, no commentary):\n"
                "{\n"
                '  "title": str,\n'
                '  "body_html": str — full HTML body with <h2>, <p>, <ul>,\n'
                '  "sections": [ {"heading": str, "body_html": str}, ... ]\n'
                "}\n"
            )
        return (
            "Return ONLY valid JSON (no markdown fences, no commentary):\n"
            "{\n"
            '  "title": str — short headline,\n'
            '  "body_html": str — full HTML body\n'
            "}\n"
        )

    # ── generation ─────────────────────────────────────────────────────

    def _generate(self, prompt: str, *, workspace_id: str, kind: str) -> dict[str, Any]:
        try:
            response = self._llm.invoke(prompt)
        except Exception:
            logger.exception(
                "interactive_draft.llm_failed workspace_id=%s kind=%s",
                workspace_id,
                kind,
            )
            return {}

        raw = getattr(response, "content", None)
        if raw is None:
            raw = str(response)

        parsed = self._extract_json(raw)
        if parsed is not None:
            return parsed
        # Plain prose — surface it as the body so the editor still gets text.
        stripped = (raw or "").strip()
        return {"body_html": stripped} if stripped else {}

    @staticmethod
    def _extract_json(raw_text: str) -> dict[str, Any] | None:
        """Best-effort recover a JSON object from chatty LLM output.

        Pure-python (no infra import). Tolerates markdown fences and
        leading/trailing prose around the JSON block.
        """
        if not raw_text:
            return None
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            pass
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            return None
