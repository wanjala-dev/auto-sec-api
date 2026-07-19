"""ORM-backed cross-context unified surface — drafts + newsletters + blogs."""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from components.content.application.ports.writing_artifacts_port import (
    WritingArtifactsPort,
    WritingArtifactSummary,
)
from components.content.domain.enums import WritingArtifactKind


def _truncate(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class WritingArtifactsRepository(WritingArtifactsPort):
    """Unions newsletters, writing drafts, and blog posts into a single
    workspace-scoped artifact list.

    Consumed by ``shared_platform``'s unified-documents controller so the
    Library tab on the frontend can render newsletter + draft + blog cards
    alongside the existing PDF/upload/import surfaces.
    """

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WritingArtifactSummary]:
        from infrastructure.persistence.content.models import (
            Newsletter,
            WritingDraft,
        )

        # News (blog) lives in a separate persistence app but in the same
        # context. Import inline to keep module-load-time Django-free.
        from infrastructure.persistence.workspaces.news.models import News

        selected_kinds = (
            set(kinds) if kinds else set(WritingArtifactKind._ALL)
        )
        items: list[WritingArtifactSummary] = []

        if WritingArtifactKind.NEWSLETTER in selected_kinds:
            for nl in Newsletter.objects.filter(
                workspace_id=workspace_id
            ).order_by("-updated_at")[: limit + offset]:
                items.append(
                    WritingArtifactSummary(
                        id=nl.id,
                        workspace_id=nl.workspace_id,
                        kind=WritingArtifactKind.NEWSLETTER,
                        source_type="newsletter",
                        title=nl.title,
                        preview=_truncate(nl.content_html),
                        status=nl.status,
                        author_id=nl.author_id,
                        created_at=nl.created_at,
                        updated_at=nl.updated_at,
                        pdf_url=None,  # presigned URL resolved by the consumer
                        metadata={"pdf_key": nl.pdf_key or ""},
                    )
                )

        if WritingArtifactKind.DRAFT in selected_kinds:
            for dr in WritingDraft.objects.filter(
                workspace_id=workspace_id
            ).order_by("-updated_at")[: limit + offset]:
                items.append(
                    WritingArtifactSummary(
                        id=dr.id,
                        workspace_id=dr.workspace_id,
                        kind=WritingArtifactKind.DRAFT,
                        source_type="writing_draft",
                        title=dr.title,
                        preview=_truncate(dr.body_html),
                        status=dr.status,
                        author_id=dr.author_id,
                        created_at=dr.created_at,
                        updated_at=dr.updated_at,
                        pdf_url=None,
                        metadata={
                            "kind": dr.kind,
                            "pdf_key": dr.pdf_key or "",
                            "ai_drafted": dr.ai_drafted,
                        },
                    )
                )

        if WritingArtifactKind.BLOG in selected_kinds:
            for blog in News.objects.filter(
                workspace_id=workspace_id
            ).order_by("-updated_at")[: limit + offset]:
                items.append(
                    WritingArtifactSummary(
                        id=blog.id,
                        workspace_id=blog.workspace_id,
                        kind=WritingArtifactKind.BLOG,
                        source_type="blog",
                        title=blog.title,
                        preview=_truncate(blog.excerpt or blog.body),
                        status=str(blog.status),
                        author_id=blog.author_id,
                        created_at=blog.created_at,
                        updated_at=blog.updated_at,
                        pdf_url=None,
                        metadata={
                            "featured": blog.featured,
                            "category_id": blog.category_id,
                        },
                    )
                )

        # Merge-sort by updated_at desc, paginate.
        items.sort(key=lambda s: s.updated_at, reverse=True)
        return items[offset : offset + limit]
