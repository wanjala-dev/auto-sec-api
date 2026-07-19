"""ORM repository for the content bounded context."""

from __future__ import annotations

from typing import Any, Optional

from django.db.models import Count, QuerySet


class ContentRepository:
    """Encapsulates all ORM access for news, categories, tags, and comments."""

    # ── Categories ──────────────────────────────────────────────────────

    def list_categories(self) -> QuerySet:
        from infrastructure.persistence.workspaces.news.models import Category
        return Category.objects.annotate(news_count=Count("entries"))

    # ── Tags ────────────────────────────────────────────────────────────

    def list_tags(self) -> QuerySet:
        from infrastructure.persistence.workspaces.news.models import Tag
        return Tag.objects.all()

    # ── News ────────────────────────────────────────────────────────────

    def get_news_queryset(self) -> QuerySet:
        # Eager-load exactly what ``NewsGetSerializer`` reads per row:
        # ``author`` is rendered by the full ``UserSerializer`` (profile →
        # country, sectors M2M, contributor_profile + its two M2Ms),
        # ``category`` is a StringRelatedField (forward FK), and ``tags`` /
        # ``workspace_comments`` / ``media`` are M2M / reverse-FK lists.
        # A bare ``.all()`` here made a 9-row news page fire 50+ queries
        # (see components/content/tests/integration/test_news_list_query_count.py).
        from infrastructure.persistence.workspaces.news.models import News
        return (
            News.objects.all()
            .select_related("author", "category")
            .prefetch_related(
                "author__profile__country",
                "author__profile__followers",
                "author__followers",
                "author__sectors",
                "author__contributor_profile__contribution_means",
                "author__contributor_profile__preferred_locations",
                "tags",
                "workspace_comments",
                "media",
            )
        )

    def get_news_with_comments(self) -> QuerySet:
        # The full read queryset already prefetches comments (and everything
        # else the read serializer touches) — one canonical eager-load.
        return self.get_news_queryset()

    def filter_news_by_workspace(self, queryset: QuerySet, workspace_id: int) -> QuerySet:
        return queryset.filter(workspace_id=workspace_id)

    def filter_news_by_slug(self, queryset: QuerySet, slug: str) -> QuerySet:
        return queryset.filter(slug=slug)

    def get_news_by_title(self, title: str):
        from infrastructure.persistence.workspaces.news.models import News
        return News.objects.get(title=title)

    # ── Comments ────────────────────────────────────────────────────────

    def get_comments_for_news(self, news_id: int) -> QuerySet:
        from infrastructure.persistence.workspaces.news.models import Comment
        return Comment.objects.filter(news=news_id)

    def get_comment_by_id(self, comment_id: int):
        from infrastructure.persistence.workspaces.news.models import Comment
        return Comment.objects.get(id=comment_id)

    def create_comment(self, *, author, news, body: str, parent=None):
        from infrastructure.persistence.workspaces.news.models import Comment
        return Comment.objects.create(
            author=author,
            news=news,
            body=body,
            parent=parent,
        )

    # ── News write ───────────────────────────────────────────────────────

    def create_news(self, *, author, **kwargs):
        from infrastructure.persistence.workspaces.news.models import News
        return News.objects.create(author=author, **kwargs)

    def update_news(self, news_id, **kwargs):
        from infrastructure.persistence.workspaces.news.models import News
        News.objects.filter(pk=news_id).update(**kwargs)
        return News.objects.get(pk=news_id)
