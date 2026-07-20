"""Composition root for the search bounded context.

Wires the Postgres suggest adapter to the :class:`SearchSuggestService`.
Provider files are the only application-layer modules allowed to import
the context's own infrastructure (Explicit Architecture composition-root
exception).
"""

from __future__ import annotations

from components.search.application.service import SearchSuggestService


def get_search_suggest_service() -> SearchSuggestService:
    from components.search.infrastructure.repositories.postgres_suggest_repository import (
        PostgresSuggestRepository,
    )

    return SearchSuggestService(index=PostgresSuggestRepository())
