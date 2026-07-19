"""Cursor-based pagination for the notifications feed.

Uses keyset pagination on ``(created_at, id)`` instead of offset-based
page numbers.  This gives O(1) page lookups regardless of dataset size,
stable ordering across concurrent writes, and no duplicate/skipped rows
when new notifications arrive between pages.

The cursor is a base64-encoded ``created_at|id`` pair. The client passes
``?cursor=<value>`` to fetch the next (or previous) page.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
from datetime import datetime

from django.utils.dateparse import parse_datetime
from rest_framework.pagination import BasePagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _encode_cursor(created_at: datetime, pk) -> str:
    """Encode a (created_at, pk) pair into a URL-safe cursor string."""
    ts = created_at.isoformat()
    raw = f"{ts}|{pk}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    """Decode a cursor string back into (created_at, pk)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, pk_str = raw.rsplit("|", 1)
        ts = parse_datetime(ts_str)
        if ts is None:
            return None
        return ts, pk_str
    except Exception:
        return None


class NotificationCursorPagination(BasePagination):
    """Keyset cursor pagination for notification feeds.

    Orders by ``-created_at, -id`` (newest first).  The cursor marks the
    last item on the current page; the next page starts after that item.
    """

    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE
    cursor_query_param = "cursor"

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        self.base_url = request.build_absolute_uri()

        # Resolve page size.
        raw_size = request.query_params.get(self.page_size_query_param)
        if raw_size:
            try:
                size = min(int(raw_size), self.max_page_size)
            except (ValueError, TypeError):
                size = self.page_size
        else:
            size = self.page_size
        self.page_size = max(size, 1)

        # Apply cursor filter if provided.
        cursor = request.query_params.get(self.cursor_query_param)
        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded:
                ts, pk = decoded
                # Keyset condition: row < cursor in (created_at DESC, id DESC)
                queryset = queryset.filter(
                    created_at__lt=ts,
                ) | queryset.filter(
                    created_at=ts,
                    pk__lt=pk,
                )

        # Order and fetch one extra row to determine has_next.
        queryset = queryset.order_by("-created_at", "-pk")
        results = list(queryset[: self.page_size + 1])

        self.has_next = len(results) > self.page_size
        if self.has_next:
            results = results[: self.page_size]

        self.page = results
        return results

    def get_next_cursor(self):
        if not self.has_next or not self.page:
            return None
        last = self.page[-1]
        return _encode_cursor(last.created_at, last.pk)

    def get_next_link(self):
        cursor = self.get_next_cursor()
        if cursor is None:
            return None
        return replace_query_param(self.base_url, self.cursor_query_param, cursor)

    def get_paginated_response(self, data):
        return Response(
            OrderedDict([
                ("next", self.get_next_link()),
                ("next_cursor", self.get_next_cursor()),
                ("page_size", self.page_size),
                ("results", data),
            ])
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "next": {"type": "string", "nullable": True},
                "next_cursor": {"type": "string", "nullable": True},
                "page_size": {"type": "integer"},
                "results": schema,
            },
        }
