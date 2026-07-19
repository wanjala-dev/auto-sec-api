"""Unit tests for the metadata decoder on ``PgVectorStoreAdapter``.

Regression test for a bug that hit prod only:  Django's raw cursor
returns ``jsonb`` columns as ``str`` on psycopg, not as ``dict``.
Downstream code calls ``.get()`` on metadata, so a string value blew up
with ``AttributeError: 'str' object has no attribute 'get'``.  The
decoder normalises the value at the adapter boundary.
"""

from __future__ import annotations

import json

from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
    _decode_metadata,
)


class TestDecodeMetadata:
    def test_dict_passes_through(self):
        payload = {"workspace_id": "ws-1", "source": "workspace_snapshot"}
        assert _decode_metadata(payload) == payload

    def test_json_string_is_decoded(self):
        payload = {"workspace_id": "ws-1", "source": "workspace_snapshot"}
        assert _decode_metadata(json.dumps(payload)) == payload

    def test_empty_string_returns_empty_dict(self):
        assert _decode_metadata("") == {}

    def test_none_returns_empty_dict(self):
        assert _decode_metadata(None) == {}

    def test_bytes_are_decoded(self):
        payload = {"k": "v"}
        assert _decode_metadata(json.dumps(payload).encode("utf-8")) == payload

    def test_malformed_json_returns_empty_dict(self):
        assert _decode_metadata("{not json") == {}

    def test_json_that_decodes_to_non_dict_returns_empty(self):
        # A JSON list or scalar is not usable metadata for us.
        assert _decode_metadata("[1, 2, 3]") == {}
        assert _decode_metadata("42") == {}
        assert _decode_metadata("null") == {}
