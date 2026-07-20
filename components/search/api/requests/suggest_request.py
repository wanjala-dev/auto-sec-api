"""Input DTO for GET /search/suggest/."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuggestRequest:
    """Validated query parameters for the suggest endpoint."""

    q: str
    limit: int | None
    workspace_id: str | None

    @classmethod
    def from_query_params(cls, query_params) -> SuggestRequest:
        raw_limit = query_params.get("limit")
        try:
            limit = int(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            limit = None
        workspace_id = (query_params.get("workspace_id") or "").strip() or None
        return cls(
            q=(query_params.get("q") or "").strip(),
            limit=limit,
            workspace_id=workspace_id,
        )
