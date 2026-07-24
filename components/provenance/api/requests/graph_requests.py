"""Query-parameter input DTOs for the provenance graph read endpoints.

Frozen dataclasses that parse ``request.query_params`` into typed values, with
safe defaults so malformed input degrades gracefully rather than erroring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

_DEFAULT_HALL_TREE_WINDOW_DAYS = 90
_DEFAULT_MAX_DEPTH = 3
_DEFAULT_UNUSED_DAYS = 30


@dataclass(frozen=True)
class HallTreeQueryRequest:
    since: datetime
    max_depth: int = _DEFAULT_MAX_DEPTH

    @classmethod
    def from_query_params(cls, params) -> HallTreeQueryRequest:
        since_raw = params.get("since")
        since = None
        if since_raw:
            try:
                since = datetime.fromisoformat(since_raw)
            except (TypeError, ValueError):
                since = None
        if since is None:
            since = timezone.now() - timedelta(days=_DEFAULT_HALL_TREE_WINDOW_DAYS)

        try:
            max_depth = max(1, int(params.get("max_depth", _DEFAULT_MAX_DEPTH)))
        except (TypeError, ValueError):
            max_depth = _DEFAULT_MAX_DEPTH
        return cls(since=since, max_depth=max_depth)


@dataclass(frozen=True)
class LeastPrivilegeQueryRequest:
    unused_days: int = _DEFAULT_UNUSED_DAYS

    @classmethod
    def from_query_params(cls, params) -> LeastPrivilegeQueryRequest:
        try:
            unused_days = max(1, int(params.get("unused_days", _DEFAULT_UNUSED_DAYS)))
        except (TypeError, ValueError):
            unused_days = _DEFAULT_UNUSED_DAYS
        return cls(unused_days=unused_days)
