"""Input DTO for GET /tagging/workspaces/<ws>/tags/ (ADR 0015 D6).

A tag picker needs the whole vocabulary, not 9/page — the default window is 200,
capped at 500 (deliberately above the global pagination default).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

# Picker-sized window (D6) — not the global 9/page default.
DEFAULT_LIMIT = 200
MAX_LIMIT = 500


def _int_param(raw, *, default: int, minimum: int, maximum: int, field: str) -> int:
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: "must be an integer"})
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ListTagsRequest:
    workspace_id: UUID
    namespace: str | None
    q: str | None
    include_usage: bool
    limit: int
    offset: int

    @classmethod
    def from_request(cls, request, workspace_id) -> ListTagsRequest:
        qp = request.query_params
        namespace = qp.get("namespace")
        return cls(
            workspace_id=workspace_id,
            namespace=namespace.strip().lower() if namespace is not None else None,
            q=(qp.get("q") or "").strip() or None,
            include_usage=(qp.get("include_usage") or "").strip().lower() in ("1", "true"),
            limit=_int_param(qp.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT, field="limit"),
            offset=_int_param(qp.get("offset"), default=0, minimum=0, maximum=10_000_000, field="offset"),
        )
