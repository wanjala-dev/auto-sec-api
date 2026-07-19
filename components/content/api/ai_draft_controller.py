"""POST endpoint that asks the writing_agent to draft body content
for an existing WritingDraft, Newsletter, or Blog (News).

Triggered by the FE editor's AskAiButton. The endpoint returns the AI's
proposed body so the editor can replace its current content. The
returned body is NOT auto-saved — the user clicks Save in the editor
to persist it. That keeps the AI strictly suggestive: a bad output
costs zero, no confirmation needed.
"""

from __future__ import annotations

import datetime
import logging
from uuid import UUID

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.api.permissions import CanComposeWriting
from components.content.application.providers.writing_ai_provider import (
    get_writing_ai_provider,
)
from components.shared_platform.api.permissions import RequiresFeatureFlag

logger = logging.getLogger(__name__)

# AI writing assists (newsletter generate / AI drafting) are a Pro feature.
_AI_WRITING_FLAG_KEY = "feature.ai_writing"


def _parse_iso_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# Upper bound on author-selected grounding documents per generation —
# each selected file adds a retrieval; an unbounded list is a cost/latency
# footgun, and no sane draft grounds on more than a handful of documents.
_MAX_GROUNDING_FILES = 10


# Chat continuity (task #31): recent turns of the assist conversation ride
# along so "now make the opening warmer" keeps meaning what the earlier
# turns established. User-authored free text, same trust level as
# ``prompt`` — capped hard so it can't balloon the prompt.
_MAX_CONVERSATION_TURNS = 6
_MAX_TURN_CHARS = 400


def _parse_conversation(value: object) -> list[dict]:
    if not isinstance(value, (list, tuple)):
        return []
    turns: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        turns.append({"role": role, "text": text[:_MAX_TURN_CHARS]})
    return turns[-_MAX_CONVERSATION_TURNS:]


def _parse_grounding_file_ids(value: object) -> list[str]:
    """Sanitise the ``grounding_file_ids`` request field: file identifiers,
    de-duplicated, capped. ``uploads.File`` pks are INTEGERS (a UUID-only
    parse silently dropped every real id — caught live 2026-07-13), but
    accept UUID strings too so a future pk migration doesn't break the
    contract. Anything else is dropped silently — document grounding is
    enrichment, not a validation surface."""
    if not isinstance(value, (list, tuple)):
        return []
    clean: list[str] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int) and item > 0:
            clean.append(str(item))
        elif isinstance(item, str):
            text = item.strip()
            if text.isdigit() and int(text) > 0:
                clean.append(str(int(text)))
            elif text.startswith("report-"):
                # Indexed financial reports (unified documents list rows) —
                # ``report-<uuid>``; the retrieval adapter maps these to the
                # ``report_id`` chunk metadata.
                try:
                    clean.append(f"report-{UUID(text.removeprefix('report-'))}")
                except (ValueError, TypeError, AttributeError):
                    continue
            else:
                try:
                    clean.append(str(UUID(text)))
                except (ValueError, TypeError, AttributeError):
                    continue
        else:
            continue
        if len(clean) >= _MAX_GROUNDING_FILES:
            break
    return list(dict.fromkeys(clean))


def _record_provenance_for_draft(*, draft_id, result: dict, prompt: str) -> dict | None:
    """Persist the run's provenance onto the draft (task #22) and return
    the trimmed document for the response. Best-effort: a bookkeeping
    failure must not turn a successful generation into a 500."""
    from django.utils import timezone

    from components.content.application.providers.writing_provider import (
        WritingProvider,
    )

    try:
        return (
            WritingProvider()
            .build_record_ai_provenance()
            .record_for_draft(draft_id=draft_id, result=result, prompt=prompt, now=timezone.now())
        )
    except Exception:
        logger.exception("ai_provenance_record_failed draft_id=%s", draft_id)
        return None


def _record_provenance_for_newsletter(*, newsletter_id, result: dict, prompt: str) -> dict | None:
    from django.utils import timezone

    from components.content.application.providers.writing_provider import (
        WritingProvider,
    )

    try:
        return (
            WritingProvider()
            .build_record_ai_provenance()
            .record_for_newsletter(newsletter_id=newsletter_id, result=result, prompt=prompt, now=timezone.now())
        )
    except Exception:
        logger.exception("ai_provenance_record_failed newsletter_id=%s", newsletter_id)
        return None


def _readable_result_text(result: dict) -> str:
    """A plain-text rendering of what the AI produced, for the chat bubble
    (the assistant message content). Prefers the body, falls back to the
    excerpt; layout-only responses still carry a fallback body."""
    from django.utils.html import strip_tags

    body = strip_tags(str(result.get("body_html") or result.get("content_html") or "")).strip()
    if body:
        return body
    return str(result.get("excerpt") or "").strip()


def _record_assist_turn(
    *, user, artifact_type: str, artifact_id, title: str, prompt: str, result: dict, grounding_file_ids: list
) -> dict:
    """Persist one assist turn (prompt + response) onto the artifact's
    document-assist Conversation so the thread survives close/reopen,
    thumbs up/down attach to the assistant message, and a published
    document can show what the AI did. Best-effort — a bookkeeping
    failure never turns a successful generation into a 500. Reuses the
    SAME conversation stack as human chat (agents service)."""
    from components.agents.application.service import AgentsService

    try:
        faithfulness = result.get("faithfulness") if isinstance(result.get("faithfulness"), dict) else {}
        response_metadata = {
            "source_chunks": result.get("source_chunks") if isinstance(result.get("source_chunks"), list) else [],
            "unsupported_numbers": faithfulness.get("unsupported_numbers") or [],
            "grounding_file_ids": [str(fid) for fid in (grounding_file_ids or [])],
            "agent_type": result.get("agent_type") or "writing_agent",
        }
        return AgentsService().record_document_assist_turn(
            user=user,
            artifact_type=artifact_type,
            artifact_id=str(artifact_id),
            title=title,
            prompt=prompt,
            response_text=_readable_result_text(result),
            response_metadata=response_metadata,
        )
    except Exception:
        logger.exception("assist_turn_record_failed artifact=%s:%s", artifact_type, artifact_id)
        return {}


class WritingDraftAskAiView(APIView):
    """POST /workspaces/news/drafts/<draft_id>/draft-with-ai/

    Body: { prompt, recipient_name?, period_start?, period_end?, topic?, tone? }
    Response: { title, body_html, excerpt, sections, agent_type }
    """

    permission_classes = (CanComposeWriting, RequiresFeatureFlag)
    feature_flag_key = _AI_WRITING_FLAG_KEY
    name = "writing-draft-ask-ai"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Resolve the AI-writing flag against the DRAFT's workspace, not the
        user's active workspace. The draft's workspace is the one that owns the
        resource being acted on; evaluating the Pro gate against the active
        workspace silently 403s a member working in a different workspace.
        """
        from components.content.application.providers.content_models_provider import get_content_models_provider

        WritingDraft = get_content_models_provider().WritingDraft
        ws_id = (
            WritingDraft.objects.filter(pk=self.kwargs.get("draft_id")).values_list("workspace_id", flat=True).first()
        )
        return str(ws_id) if ws_id else None

    def post(self, request, draft_id: UUID):
        from components.content.application.providers.content_models_provider import get_content_models_provider

        WritingDraft = get_content_models_provider().WritingDraft

        draft = WritingDraft.objects.filter(pk=draft_id).first()
        if draft is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        adapter = get_writing_ai_provider().adapter()
        if not adapter.is_configured():
            return Response(
                {"detail": ("AI writing assist is not configured for this environment yet.")},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Designed drafts (task #19): the layout comes from the draft row
        # itself (server-side truth), never the request body. When a
        # designed-capable draft is still BLANK (no layout, no body typed),
        # the kind's default design template layout applies so the AI
        # generates INTO a designed document — same per-field completion +
        # guards a template-composed draft gets. Kinds with no design
        # template (letters) resolve None and keep the prose path.
        existing_layout = (draft.metadata or {}).get("layout")
        has_layout = isinstance(existing_layout, dict) and existing_layout.get("blocks")
        draft_is_blank = (
            not (draft.body_html or "").strip() and not str(request.data.get("existing_body_html") or "").strip()
        )
        if not has_layout and draft_is_blank:
            from components.content.application.providers.writing_provider import (
                WritingProvider,
            )

            existing_layout = (
                WritingProvider()
                .build_resolve_default_design_layout()
                .execute(workspace_id=draft.workspace_id, kind=draft.kind)
            )
        elif not has_layout:
            existing_layout = None

        prompt = (request.data.get("prompt") or "").strip()
        grounding_file_ids = _parse_grounding_file_ids(request.data.get("grounding_file_ids"))
        result = adapter.draft_for_kind(
            kind=draft.kind,
            workspace_id=str(draft.workspace_id),
            title=(draft.title or "").strip(),
            prompt=prompt,
            recipient_name=(request.data.get("recipient_name") or "").strip(),
            period_start=_parse_iso_date(request.data.get("period_start")),
            period_end=_parse_iso_date(request.data.get("period_end")),
            topic=(request.data.get("topic") or "").strip(),
            tone=(request.data.get("tone") or "").strip(),
            related_entity_type=(draft.related_entity_type or ""),
            related_entity_id=(str(draft.related_entity_id) if draft.related_entity_id else ""),
            grounding_file_ids=grounding_file_ids,
            existing_body_html=str(request.data.get("existing_body_html") or "")[:20000],
            existing_layout=existing_layout,
            conversation=_parse_conversation(request.data.get("conversation")),
        )
        result["ai_provenance"] = _record_provenance_for_draft(
            draft_id=draft_id,
            result=result,
            prompt=prompt,
        )
        turn = _record_assist_turn(
            user=request.user,
            artifact_type="writing_draft",
            artifact_id=draft_id,
            title=(draft.title or "Draft"),
            prompt=prompt,
            result=result,
            grounding_file_ids=grounding_file_ids,
        )
        result["assist_conversation_id"] = turn.get("conversation_id")
        result["assist_message_id"] = turn.get("assistant_message_id")
        return Response(result, status=status.HTTP_200_OK)


class NewsletterAskAiView(APIView):
    """POST /workspaces/news/newsletters/<id>/draft-with-ai/

    Used by the Newsletter editor's AskAi button — same shape as the
    draft endpoint but always routes to the newsletter-shaped tool.
    """

    permission_classes = (CanComposeWriting, RequiresFeatureFlag)
    feature_flag_key = _AI_WRITING_FLAG_KEY
    name = "newsletter-ask-ai"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Resolve the AI-writing flag against the NEWSLETTER's workspace, not
        the user's active workspace (see WritingDraftAskAiView for rationale).
        """
        from components.content.application.providers.content_models_provider import get_content_models_provider

        Newsletter = get_content_models_provider().Newsletter
        ws_id = (
            Newsletter.objects.filter(pk=self.kwargs.get("newsletter_id"))
            .values_list("workspace_id", flat=True)
            .first()
        )
        return str(ws_id) if ws_id else None

    def post(self, request, newsletter_id: UUID):
        from components.content.application.providers.content_models_provider import get_content_models_provider

        Newsletter = get_content_models_provider().Newsletter

        newsletter = Newsletter.objects.filter(pk=newsletter_id).first()
        if newsletter is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        adapter = get_writing_ai_provider().adapter()
        if not adapter.is_configured():
            return Response(
                {"detail": ("AI writing assist is not configured for this environment yet.")},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        prompt = (request.data.get("prompt") or "").strip()
        grounding_file_ids = _parse_grounding_file_ids(request.data.get("grounding_file_ids"))
        result = adapter.draft_for_kind(
            kind="newsletter",
            workspace_id=str(newsletter.workspace_id),
            title=(newsletter.title or "").strip(),
            prompt=prompt,
            period_start=_parse_iso_date(request.data.get("period_start")) or newsletter.period_start,
            period_end=_parse_iso_date(request.data.get("period_end")) or newsletter.period_end,
            grounding_file_ids=grounding_file_ids,
            existing_body_html=str(request.data.get("existing_body_html") or "")[:20000],
            # Designed newsletters (template-composed) carry a block layout —
            # the AI completes IT (per-field, with the guards), not just the
            # fallback body the preview never renders (Henry hit exactly
            # this: AI changes "not saved").
            existing_layout=(newsletter.content_payload or {}).get("layout"),
            conversation=_parse_conversation(request.data.get("conversation")),
        )
        result["ai_provenance"] = _record_provenance_for_newsletter(
            newsletter_id=newsletter_id,
            result=result,
            prompt=prompt,
        )
        turn = _record_assist_turn(
            user=request.user,
            artifact_type="newsletter",
            artifact_id=newsletter_id,
            title=(newsletter.title or "Newsletter"),
            prompt=prompt,
            result=result,
            grounding_file_ids=grounding_file_ids,
        )
        result["assist_conversation_id"] = turn.get("conversation_id")
        result["assist_message_id"] = turn.get("assistant_message_id")
        return Response(result, status=status.HTTP_200_OK)


class WritingDraftAssistThreadView(APIView):
    """GET /workspaces/news/drafts/<draft_id>/assist-thread/

    Returns the current user's document-assist conversation id for this
    draft so the editor (and the read-only "AI assisted" view on a
    published draft) can load the thread through the existing
    ``/ai/conversations/<id>/messages/`` endpoint — same mechanism as
    human chat history. ``conversation_id`` is null when the user has
    never used AI assist on this draft.
    """

    permission_classes = (CanComposeWriting,)
    name = "writing-draft-assist-thread"

    def get(self, request, draft_id: UUID):
        from components.agents.application.service import AgentsService

        conversation_id = AgentsService().find_document_assist_conversation_id(
            user=request.user, artifact_type="writing_draft", artifact_id=str(draft_id)
        )
        return Response({"conversation_id": conversation_id}, status=status.HTTP_200_OK)


class NewsletterAssistThreadView(APIView):
    """GET /workspaces/news/newsletters/<newsletter_id>/assist-thread/ — see
    WritingDraftAssistThreadView."""

    permission_classes = (CanComposeWriting,)
    name = "newsletter-assist-thread"

    def get(self, request, newsletter_id: UUID):
        from components.agents.application.service import AgentsService

        conversation_id = AgentsService().find_document_assist_conversation_id(
            user=request.user, artifact_type="newsletter", artifact_id=str(newsletter_id)
        )
        return Response({"conversation_id": conversation_id}, status=status.HTTP_200_OK)
