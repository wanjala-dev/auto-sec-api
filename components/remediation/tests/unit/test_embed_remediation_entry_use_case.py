"""Unit tests — embed-on-capture builds a workspace-scoped remediation_entry chunk (ADR 0012 P4).

No DB, no embeddings: a fake ``CorpusChunkIndexPort`` records exactly what the use
case hands it, so we assert the retrieval contract — the metadata the triage advisor
later filters on (``chunk_type`` + ``workspace_id`` + ``finding_kind``) and the stable
per-entry document key that makes re-embedding idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.remediation.application.ports.remediation_retrieval_port import (
    REMEDIATION_CHUNK_TYPE,
)
from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
    EmbedRemediationEntryUseCase,
    document_key_for,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry


class _FakeIndex:
    def __init__(self) -> None:
        self.indexed: list[dict] = []
        self.deleted: list[str] = []

    def index_chunk(self, *, document_key: str, content: str, metadata: dict) -> int:
        self.indexed.append({"document_key": document_key, "content": content, "metadata": metadata})
        return 1

    def delete_by_key(self, *, document_key: str) -> int:
        self.deleted.append(document_key)
        return 1


def _entry(*, workspace_id, finding_kind="log_watch", code="alias = Real\n") -> RemediationEntry:
    return RemediationEntry(
        id=uuid4(),
        workspace_id=workspace_id,
        finding_kind=finding_kind,
        source_type=f"ai.{finding_kind}",
        tags=("import", "casing"),
        language="python",
        code=code,
        title="Fix casing ImportError",
        summary="Add a casing alias instead of deleting the module.",
        finding_task_id="task-1",
        finding_fingerprint="fp-1",
        provenance_event_ref="prov-1",
        applied_pr_url="https://github.com/org/repo/pull/1",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
    )


@pytest.mark.unit
class TestEmbedRemediationEntry:
    def test_indexes_workspace_scoped_remediation_chunk(self):
        ws = uuid4()
        entry = _entry(workspace_id=ws)
        index = _FakeIndex()

        written = EmbedRemediationEntryUseCase(index=index).execute(entry)

        assert written == 1
        assert len(index.indexed) == 1
        call = index.indexed[0]
        meta = call["metadata"]
        # The retrieval discriminators — the load-bearing filter surface.
        assert meta["chunk_type"] == REMEDIATION_CHUNK_TYPE
        assert meta["workspace_id"] == str(ws)
        assert meta["finding_kind"] == "log_watch"
        assert meta["source_type"] == "ai.log_watch"
        assert meta["entry_id"] == str(entry.id)
        # RAW fix carried for the advisor (D3: raw text, never rendered HTML).
        assert meta["language"] == "python"
        assert "alias = Real" in meta["code"]
        assert meta["tags"] == ["import", "casing"]
        # Searchable content leads with the finding context, includes the fix.
        assert "log_watch" in call["content"]
        assert "alias = Real" in call["content"]

    def test_document_key_is_stable_per_entry_for_idempotent_reembed(self):
        entry = _entry(workspace_id=uuid4())
        index = _FakeIndex()

        EmbedRemediationEntryUseCase(index=index).execute(entry)
        EmbedRemediationEntryUseCase(index=index).execute(entry)

        # Same key both times → the adapter replaces in place (never duplicates).
        assert index.indexed[0]["document_key"] == document_key_for(str(entry.id))
        assert index.indexed[1]["document_key"] == index.indexed[0]["document_key"]
