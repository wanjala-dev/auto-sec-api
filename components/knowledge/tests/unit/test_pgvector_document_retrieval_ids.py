"""Unit tests: the document-retrieval filter's three id families (task #23).

PDF uploads tag ``pdf_id``, docx uploads ``file_id`` (integer pks), and
indexed financial reports ``report_id`` (UUID strings, arriving from the
unified documents list as ``report-<uuid>``). The adapter must route each
id to the right metadata branch — a report id in the pk branches (or vice
versa) silently grounds nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from components.knowledge.infrastructure.adapters.pgvector_document_retrieval_adapter import (
    PgVectorDocumentRetrievalAdapter,
)

_REPORT_UUID = "fbcf893b-2633-4348-9b62-435f89c0f663"


def _search(file_ids):
    store = MagicMock()
    store.similarity_search_with_score.return_value = []
    with patch(
        "components.knowledge.infrastructure.factories.vector_stores.factory.VectorStoreFactory.create_vector_store",
        return_value=store,
    ):
        PgVectorDocumentRetrievalAdapter().search(workspace_id="ws-1", query="q", file_ids=file_ids)
    _, kwargs = store.similarity_search_with_score.call_args
    return kwargs["filter"]["$and"][1]["$or"]


class TestIdRouting:
    def test_integer_pks_hit_pdf_and_file_branches(self):
        branches = _search(["7", "9"])
        assert {"pdf_id": {"$in": ["7", "9"]}} in branches
        assert {"file_id": {"$in": ["7", "9"]}} in branches
        assert not any("report_id" in b for b in branches)

    def test_report_prefixed_ids_hit_report_branch_stripped(self):
        branches = _search([f"report-{_REPORT_UUID}"])
        assert branches == [{"report_id": {"$in": [_REPORT_UUID]}}]

    def test_mixed_ids_route_to_their_families(self):
        branches = _search(["7", f"report-{_REPORT_UUID}"])
        assert {"pdf_id": {"$in": ["7"]}} in branches
        assert {"file_id": {"$in": ["7"]}} in branches
        assert {"report_id": {"$in": [_REPORT_UUID]}} in branches
