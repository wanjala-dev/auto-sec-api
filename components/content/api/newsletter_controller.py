"""Views for Newsletter CRUD + send action + on-demand generation.

Thin entry points. Each view instantiates a use case via ``WritingProvider``
and returns the entity (or DTO) shaped into JSON via the serializer.

Authorization: workspace-scoped RBAC via
``components.content.api.permissions``. Reads gate on ``view_writing``;
mutations gate on ``manage_writing``; send / schedule / regenerate gate
on the narrower ``manage_newsletter_send`` (owner / admin only). The
permission classes themselves resolve the workspace from URL kwargs,
request body, or active workspace, then check WorkspaceMembership.role
per ADR 0002 — no separate membership middleware needed.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.api.permissions import (
    CanComposeWriting,
    CanReadWriting,
    CanSendNewsletter,
)
from components.content.application.providers.writing_provider import WritingProvider
from components.content.domain.errors import (
    NewsletterAlreadySentError,
    NewsletterNotFoundError,
    NewsletterUnverifiedFiguresError,
)
from components.shared_platform.api.permissions import RequiresFeatureFlag


def _unverified_figures_response(exc: NewsletterUnverifiedFiguresError) -> Response:
    """422 with the unverified figures so the UI can offer an override."""
    return Response(
        {
            "detail": (
                "This newsletter cites figures we couldn't verify against your "
                "workspace data. Review them, or send anyway."
            ),
            "code": "unverified_figures",
            "unsupported_numbers": list(exc.result.unsupported_numbers),
            "unsupported_names": list(exc.result.unsupported_names),
            "checked": exc.result.checked,
        },
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


logger = logging.getLogger(__name__)

# AI writing assists (newsletter generate / AI drafting) are a Pro feature.
_AI_WRITING_FLAG_KEY = "feature.ai_writing"


class NewsletterSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    workspace_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    content_html = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField(read_only=True)
    scheduled_for = serializers.DateTimeField(allow_null=True, required=False)
    sent_at = serializers.DateTimeField(allow_null=True, read_only=True)
    pdf_key = serializers.CharField(read_only=True)
    period_start = serializers.DateField(allow_null=True, required=False)
    period_end = serializers.DateField(allow_null=True, required=False)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


def _resolve_ai_provenance(entity) -> dict | None:
    """Canonical ``metadata.ai_provenance`` (written by ask-ai), falling
    back to a synthesized document for generate-flow rows that stored raw
    ``metadata.source_chunks`` before provenance persistence existed."""
    metadata = getattr(entity, "metadata", {}) or {}
    provenance = metadata.get("ai_provenance")
    if isinstance(provenance, dict):
        return provenance
    legacy_chunks = metadata.get("source_chunks")
    if not isinstance(legacy_chunks, list) or not legacy_chunks:
        return None
    return {
        "generated_at": entity.created_at.isoformat(),
        "prompt": "",
        "agent_type": getattr(entity, "ai_drafted_by_agent", "") or "",
        "source_chunks": [
            {
                "section": str(c.get("section") or ""),
                "section_title": str(c.get("section_title") or ""),
                "score": c.get("score"),
                "excerpt": str(c.get("content") or c.get("excerpt") or "")[:280],
            }
            for c in legacy_chunks[:12]
            if isinstance(c, dict)
        ],
        "faithfulness": {},
    }


def _serialize(entity, *, include_rendered: bool = False) -> dict[str, Any]:
    # ``layout`` is the typed block tree the FE renders. AI-drafted
    # newsletters get one synthesized by
    # ``GenerateNewsletterUseCase``; legacy / human-drafted rows have
    # an empty payload and the FE falls back to rendering ``content_html``.
    payload = getattr(entity, "content_payload", {}) or {}
    layout = payload.get("layout") or None
    preheader = getattr(entity, "preheader", "") or ""
    result = {
        "id": str(entity.id),
        "workspace_id": str(entity.workspace_id),
        "title": entity.title,
        "subject": getattr(entity, "subject", "") or "",
        "preheader": preheader,
        "from_name": getattr(entity, "from_name", "") or "",
        "reply_to": getattr(entity, "reply_to", "") or "",
        "content_html": entity.content_html,
        "layout": layout,
        "status": entity.status,
        "scheduled_for": entity.scheduled_for.isoformat() if entity.scheduled_for else None,
        "sent_at": entity.sent_at.isoformat() if entity.sent_at else None,
        "pdf_key": entity.pdf_key,
        "period_start": entity.period_start.isoformat() if entity.period_start else None,
        "period_end": entity.period_end.isoformat() if entity.period_end else None,
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
        # AI provenance (task #22) — which sources the last AI assist
        # cited, persisted under metadata by the ask-ai endpoint. Older
        # generate-flow rows stored raw ``source_chunks`` in metadata;
        # synthesize the same shape so their drawer isn't empty.
        "ai_provenance": _resolve_ai_provenance(entity),
        # Send metrics (task #25) — denormalized counters, free to read.
        # ``stats`` is null until a tracked send exists (recipient_count
        # is None for sends that predate tracking) so the UI can hide
        # metrics instead of showing a false zero.
        "stats": (
            {
                "recipients": entity.recipient_count,
                "failed": entity.failed_count or 0,
                "unique_opens": entity.unique_open_count,
                "total_opens": entity.total_open_count,
                "last_opened_at": (entity.last_opened_at.isoformat() if entity.last_opened_at else None),
            }
            if getattr(entity, "recipient_count", None) is not None
            else None
        ),
    }
    # ``rendered_html`` is the exact email-safe HTML the inbox + PDF receive,
    # produced by the single render port. The detail view includes it so the
    # in-app preview shows the real email (preview == sent). Computed only for
    # detail — rendering it per row in the list would be wasteful.
    if include_rendered:
        from components.content.application.providers.newsletter_html_render_provider import (
            get_newsletter_html_render_provider,
        )

        result["rendered_html"] = (
            get_newsletter_html_render_provider()
            .renderer()
            .render(
                layout=layout,
                fallback_html=entity.content_html,
                context={"preheader": preheader},
            )
        )
    return result


# The layout-placeholder resolver moved to the shared application service so
# the compose-a-draft-from-a-template path reuses it (task #19). The local
# name is kept as an alias for existing imports/tests.
from components.content.application.services.layout_placeholder_service import (  # noqa: E402
    resolve_layout_placeholders as _resolve_layout_placeholders,
)


class NewsletterListView(APIView):
    """GET lists newsletters; POST creates an empty one (optionally seeded
    from a writing template).

    The POST path is what the compose-from-template flow calls — the
    user picked a kind=newsletter template, the FE wizard couldn't
    target ``/content/drafts/`` (Newsletter is a separate model, not a
    WritingDraft kind), so this endpoint is the explicit "create a
    blank newsletter, optionally pre-filled from this template" path.
    Result lands at ``status=draft`` so the editor opens it ready to
    edit; sending is still a separate explicit action.
    """

    name = "newsletter-list"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanComposeWriting()]

    def get(self, request):
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query param required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from components.content.application.providers.newsletter_read_repository_provider import (
            get_newsletter_read_repository_provider,
        )

        status_filter = request.query_params.get("status")
        items = (
            get_newsletter_read_repository_provider()
            .repository()
            .list_for_workspace(
                workspace_id=UUID(workspace_id),
                status=status_filter,
                limit=int(request.query_params.get("limit", 100)),
                offset=int(request.query_params.get("offset", 0)),
            )
        )
        return Response({"results": [_serialize(i) for i in items]})

    def post(self, request):
        workspace_id_raw = request.data.get("workspace_id")
        title = (request.data.get("title") or "").strip()
        if not workspace_id_raw or not title:
            return Response(
                {"detail": "workspace_id and title required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            workspace_id = UUID(workspace_id_raw)
        except (ValueError, TypeError):
            return Response(
                {"detail": "workspace_id must be a UUID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional template seed. When the FE Templates page's "Use this
        # template" flow lands a newsletter-kind template, the wizard
        # passes ``template_id`` so we copy the template body into the
        # new newsletter. Falls back to an empty body when no template
        # is supplied.
        content_html = request.data.get("content_html") or ""
        content_payload = None
        template_id_raw = request.data.get("template_id")
        if template_id_raw and not content_html:
            try:
                template_id = UUID(template_id_raw)
            except (ValueError, TypeError):
                return Response(
                    {"detail": "template_id must be a UUID"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            from components.content.application.providers.writing_template_repository_provider import (
                get_writing_template_repository_provider,
            )

            template = get_writing_template_repository_provider().repository().get(template_id=template_id)
            if template is not None:
                resolver = None
                try:
                    from components.content.application.providers.template_placeholder_provider import (
                        get_template_placeholder_provider,
                    )

                    resolver = get_template_placeholder_provider().resolver()
                except Exception:
                    logger.exception(
                        "newsletter template resolver load failed template_id=%s",
                        template_id,
                    )

                # Prose fallback (letter-style templates) — resolve workspace
                # placeholders so the editor opens with real numbers, not
                # literal {{tokens}}.
                content_html = template.body_html or ""
                if resolver is not None and content_html:
                    try:
                        content_html = resolver.resolve(body_html=content_html, workspace_id=workspace_id)
                    except Exception:
                        logger.exception(
                            "newsletter create template resolve failed template_id=%s",
                            template_id,
                        )

                # Design templates (kind=newsletter) carry a block-tree layout
                # in ``metadata['layout']``. Copy it into the new newsletter so
                # it renders as the designed newsletter through the SEE-178
                # render engine — with placeholders resolved to workspace data.
                layout = (template.metadata or {}).get("layout")
                if isinstance(layout, dict) and layout.get("blocks"):
                    # Resolve the workspace donate link so a design's
                    # "Get Involved" CTA points at the real public donate page
                    # ({{donate_url}} → FRONTEND_URL/donate/workspace/<id>).
                    # Best-effort: an empty link makes the CTA renderer drop the
                    # block rather than ship a dead button.
                    donate_url = ""
                    try:
                        from components.content.application.use_cases.generate_newsletter_use_case import (
                            _workspace_donate_url,
                        )

                        donate_url = _workspace_donate_url(workspace_id) or ""
                    except Exception:
                        logger.exception(
                            "newsletter donate-url resolve failed workspace_id=%s",
                            workspace_id,
                        )
                    content_payload = {
                        "layout": _resolve_layout_placeholders(layout, resolver, workspace_id, donate_url)
                    }

        from components.content.application.providers.newsletter_store_repository_provider import (
            get_newsletter_store_repository_provider,
        )
        from components.content.domain.enums import NewsletterStatus

        entity = (
            get_newsletter_store_repository_provider()
            .repository()
            .create(
                workspace_id=workspace_id,
                title=title,
                content_html=content_html,
                status=NewsletterStatus.DRAFT,
                author_id=request.user.id,
                content_payload=content_payload,
            )
        )
        return Response(_serialize(entity, include_rendered=True), status=status.HTTP_201_CREATED)


class NewsletterDetailView(APIView):
    """GET reads, PATCH composes — different permission gates per method.

    GET is authenticated-only at the route level; the real read gate is
    object-level in ``_may_read``: staff with the writing surface read
    everything, while a SENT newsletter is published, donor-facing content
    (the send already fanned it out to sponsor feeds and inboxes) so any
    active member of its workspace — sponsors/viewers included — may read
    it. Unsent drafts stay behind ``view_writing``.
    """

    name = "newsletter-detail"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [CanComposeWriting()]

    def _may_read(self, request, entity) -> bool:
        if CanReadWriting().has_permission(request, self):
            return True
        is_sent = bool(getattr(entity, "sent_at", None)) or (getattr(entity, "status", "") == "sent")
        if not is_sent:
            return False
        from components.membership.api.permissions import (
            user_is_active_workspace_member,
        )

        return user_is_active_workspace_member(request.user, entity.workspace_id)

    def get(self, request, newsletter_id: UUID):
        from components.content.application.providers.newsletter_read_repository_provider import (
            get_newsletter_read_repository_provider,
        )

        entity = get_newsletter_read_repository_provider().repository().get(newsletter_id=newsletter_id)
        if entity is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not self._may_read(request, entity):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(_serialize(entity, include_rendered=True))

    def patch(self, request, newsletter_id: UUID):
        from components.content.application.providers.newsletter_store_repository_provider import (
            get_newsletter_store_repository_provider,
        )

        title = request.data.get("title")
        content_html = request.data.get("content_html")
        if title is None or content_html is None:
            return Response(
                {"detail": "title and content_html required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Optional pre-send guardrail fields. ``None`` means "don't
        # touch this column" so legacy editors that don't know about
        # them keep working; empty string is a legitimate "clear this
        # override" signal.
        subject = request.data.get("subject")
        preheader = request.data.get("preheader")
        from_name = request.data.get("from_name")
        reply_to = request.data.get("reply_to")
        # AI-completed (or hand-edited) design — persists as the layout the
        # preview/send/PDF render, so staged AI changes become the latest
        # version on Save.
        layout = request.data.get("layout")
        if layout is not None and not (isinstance(layout, dict) and layout.get("blocks")):
            return Response(
                {"detail": "layout must be a block-tree object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            entity = (
                get_newsletter_store_repository_provider()
                .repository()
                .update_body(
                    newsletter_id=newsletter_id,
                    title=title,
                    content_html=content_html,
                    subject=subject,
                    preheader=preheader,
                    from_name=from_name,
                    reply_to=reply_to,
                    layout=layout,
                )
            )
        except NewsletterNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(entity, include_rendered=True))


class NewsletterSendView(APIView):
    """POST endpoint — the ONLY path to status=SENT (human-triggered).

    Gate: ``manage_newsletter_send`` (owner/admin only). Contributors
    can compose but cannot trigger a real send — they go through the
    approval workflow (Phase 2) or hand off to an admin.
    """

    permission_classes = (CanSendNewsletter,)
    name = "newsletter-send"

    def post(self, request, newsletter_id: UUID):
        use_case = WritingProvider().build_send_newsletter()
        override_unverified = bool(request.data.get("override_unverified"))
        try:
            sent = use_case.execute(
                newsletter_id=newsletter_id,
                triggered_by_user_id=request.user.id,
                now=timezone.now(),
                override_unverified=override_unverified,
            )
        except NewsletterNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except NewsletterUnverifiedFiguresError as exc:
            return _unverified_figures_response(exc)
        except NewsletterAlreadySentError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_serialize(sent))


class NewsletterGenerateView(APIView):
    """POST endpoint — on-demand AI-drafted newsletter for a period.

    Gate: ``manage_writing`` — composing an AI draft is a write action
    (creates a Newsletter row), but does NOT send. Anyone authorized to
    compose can spin one up; only ``manage_newsletter_send`` holders can
    actually dispatch the result.
    """

    permission_classes = (CanComposeWriting, RequiresFeatureFlag)
    feature_flag_key = _AI_WRITING_FLAG_KEY
    name = "newsletter-generate"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Resolve the AI-writing flag against the TARGET workspace carried in
        the request body, not the user's active workspace. The generate call
        names the workspace it acts on; falling back to the active workspace
        silently 403s a member generating for a different workspace.
        """
        ws_id = request.data.get("workspace_id") if request is not None else None
        return str(ws_id) if ws_id else None

    def post(self, request):
        workspace_id = request.data.get("workspace_id")
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        if not all([workspace_id, period_start, period_end]):
            return Response(
                {"detail": "workspace_id, period_start, period_end required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Dispatch as a Celery task so the HTTP request returns
        # immediately. Generation runs in the AI worker queue.
        from components.content.workers.tasks import generate_newsletter_draft

        # ``force=true`` bypasses the (workspace, period) idempotency
        # check and overwrites the existing draft in place. Used by the
        # editor's "Regenerate" action so the operator can refresh an
        # AI draft with the current workspace state without creating a
        # duplicate newsletter row.
        force = bool(request.data.get("force"))

        async_result = generate_newsletter_draft.delay(
            workspace_id=str(workspace_id),
            period_start=str(period_start),
            period_end=str(period_end),
            metrics={},
            user_guidance=request.data.get("user_guidance", ""),
            force=force,
        )
        return Response(
            {"task_id": async_result.id, "status": "pending"},
            status=status.HTTP_202_ACCEPTED,
        )


class NewsletterSendTestView(APIView):
    """POST endpoint — send a test copy of the newsletter to the caller.

    Used by the pre-send confirm modal so the operator can verify the
    rendered email + footer + unsubscribe link before triggering a
    real send. Subject is prefixed ``[TEST]``; the newsletter row's
    status is NOT changed.

    Gated on ``manage_newsletter_send`` because the caller still pays
    for an SES outbound — wouldn't want a viewer-role user spamming
    themselves at the workspace's expense.
    """

    permission_classes = (CanSendNewsletter,)
    name = "newsletter-send-test"

    def post(self, request, newsletter_id: UUID):
        recipient_email = request.user.email
        if not recipient_email:
            return Response(
                {"detail": "calling user has no email address"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        recipient_name = (
            (getattr(request.user, "first_name", "") or "") + " " + (getattr(request.user, "last_name", "") or "")
        ).strip()

        use_case = WritingProvider().build_send_test_newsletter()
        override_unverified = bool(request.data.get("override_unverified"))
        try:
            use_case.execute(
                newsletter_id=newsletter_id,
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                override_unverified=override_unverified,
            )
        except NewsletterNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except NewsletterUnverifiedFiguresError as exc:
            return _unverified_figures_response(exc)
        return Response(
            {"status": "test_sent", "recipient": recipient_email},
            status=status.HTTP_202_ACCEPTED,
        )


class NewsletterExportPdfView(APIView):
    permission_classes = (CanReadWriting,)
    name = "newsletter-export-pdf"

    def post(self, request, newsletter_id: UUID):
        from components.content.workers.tasks import render_newsletter_pdf

        async_result = render_newsletter_pdf.delay(str(newsletter_id))
        return Response(
            {"task_id": async_result.id, "status": "pending"},
            status=status.HTTP_202_ACCEPTED,
        )
