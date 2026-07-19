"""Application service for the content bounded context.

This is the PRIMARY PORT — driving adapters (controllers, CLI, GraphQL)
call these methods to trigger application use cases. The service
orchestrates repositories and use cases; it contains no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.content.infrastructure.repositories.content_repository import (
    ContentRepository,
)


@dataclass
class ContentService:
    """Primary port for the content bounded context.

    Controllers and other driving adapters depend on this interface.
    """

    _repo: ContentRepository = field(default_factory=ContentRepository)

    # ── Category queries ────────────────────────────────────────────────

    def list_categories(self):
        return self._repo.list_categories()

    # ── Tag queries ─────────────────────────────────────────────────────

    def list_tags(self):
        return self._repo.list_tags()

    # ── News queries ────────────────────────────────────────────────────

    def get_news_queryset(self):
        return self._repo.get_news_queryset()

    def get_news_with_comments(self):
        return self._repo.get_news_with_comments()

    def filter_news_by_workspace(self, queryset, workspace_id):
        return self._repo.filter_news_by_workspace(queryset, workspace_id)

    def filter_news_by_slug(self, queryset, slug: str):
        return self._repo.filter_news_by_slug(queryset, slug)

    def get_news_by_title(self, title: str):
        return self._repo.get_news_by_title(title)

    # ── Comment queries ─────────────────────────────────────────────────

    def get_comments_for_news(self, news_id: int):
        return self._repo.get_comments_for_news(news_id)

    def get_comment_by_id(self, comment_id: int):
        return self._repo.get_comment_by_id(comment_id)

    def create_comment(self, *, author_id, news_title: str, body: str, parent_id=None):
        news = self._repo.get_news_by_title(news_title)
        parent = self._repo.get_comment_by_id(parent_id) if parent_id else None
        return self._repo.create_comment(
            author=author_id,
            news=news,
            body=body,
            parent=parent,
        )

    def create_comment_reply(self, *, author_id, parent_comment_id: int, body: str):
        parent = self._repo.get_comment_by_id(parent_comment_id)
        return self._repo.create_comment(
            author=author_id,
            news=parent.news,
            body=body,
            parent=parent,
        )
