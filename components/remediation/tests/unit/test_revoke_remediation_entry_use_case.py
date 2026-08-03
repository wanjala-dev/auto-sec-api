"""Unit tests — governance-gated revocation (ADR 0012 P5).

The security spine of P5. Proves:
- **gated**: an unauthorized caller is REFUSED and nothing is mutated (fail-closed);
  owner/admin OR sign-off-approved authorizes.
- **removes from BOTH stores**: the corpus row is soft-deleted AND the embedding is
  deleted — proven end-to-end by a shared in-memory corpus that BOTH the revoke use
  case (delete side) and the retrieval adapter (read side) share, so
  "revoke ⇒ retrieval returns nothing for it" is demonstrated, not asserted.
- **audited**: a revocation emits exactly one provenance record.
- **tenant-scoped**: a foreign id revokes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.remediation.application.commands.revoke_remediation_entry_command import (
    RevokeRemediationEntryCommand,
)
from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
    EmbedRemediationEntryUseCase,
)
from components.remediation.application.use_cases.revoke_remediation_entry_use_case import (
    RevokeRemediationEntryUseCase,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.errors import RevocationNotAuthorizedError
from components.remediation.infrastructure.adapters.pgvector_remediation_retrieval_adapter import (
    PgVectorRemediationRetrievalAdapter,
)
from components.remediation.tests.unit.fakes import FakeSignOffGate, FakeStore

pytestmark = pytest.mark.unit

_WS = uuid4()


def _entry(*, workspace_id=_WS, finding_kind="log_watch"):
    return RemediationEntry(
        id=uuid4(),
        workspace_id=workspace_id,
        finding_kind=finding_kind,
        source_type="ai." + finding_kind,
        tags=(),
        language="python",
        code="alias = Real",
        title="Fix casing import",
        summary="rename",
        finding_task_id="t-1",
        finding_fingerprint="fp-1",
        provenance_event_ref="agent:triage@t1",
        applied_pr_url="https://github.com/acme/repo/pull/1",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
        score=3,
    )


class _InMemoryCorpus:
    """A single dict that behaves as BOTH the knowledge ``CorpusChunkIndexPort``
    (index/delete by key) AND a ``VectorStorePort`` (metadata-filtered search) — so a
    revocation's embedding-delete and retrieval read the SAME store."""

    def __init__(self) -> None:
        self.chunks: dict[str, dict] = {}  # document_key -> {content, metadata, score}

    # CorpusChunkIndexPort
    def index_chunk(self, *, document_key: str, content: str, metadata: dict) -> int:
        self.chunks[document_key] = {
            "content": content,
            "metadata": {**metadata, "document_key": document_key},
            "score": 0.9,
        }
        return 1

    def delete_by_key(self, *, document_key: str) -> int:
        return 1 if self.chunks.pop(document_key, None) is not None else 0

    # VectorStorePort-ish
    def search(self, query, *, k=5, filters=None):
        from components.knowledge.application.ports.vector_store_port import RetrievedChunk

        out = []
        for row in self.chunks.values():
            meta = row["metadata"]
            if all(str(meta.get(key)) == str(val) for key, val in (filters or {}).items()):
                out.append(RetrievedChunk(content=row["content"], metadata=meta, score=row["score"]))
        return out[:k]


class _FakeGovernance:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed

    def can_revoke(self, *, workspace_id, actor_user_id) -> bool:
        return self._allowed


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def log_revocation(self, *, entry_id, workspace_id, actor_id, reason) -> None:
        self.calls.append({"entry_id": entry_id, "workspace_id": workspace_id, "actor_id": actor_id, "reason": reason})


def _build(*, store, corpus, governance_allowed=True, approved=False, audit=None):
    return RevokeRemediationEntryUseCase(
        store=store,
        corpus_index=corpus,
        governance=_FakeGovernance(allowed=governance_allowed),
        sign_off_gate=FakeSignOffGate(approved=approved),
        audit=audit or _RecordingAudit(),
    )


class TestAuthorization:
    def test_unauthorized_caller_is_refused_and_nothing_mutated(self):
        store, corpus = FakeStore(), _InMemoryCorpus()
        entry = _entry()
        store.save(entry)
        EmbedRemediationEntryUseCase(index=corpus).execute(entry)
        uc = _build(store=store, corpus=corpus, governance_allowed=False, approved=False)

        with pytest.raises(RevocationNotAuthorizedError):
            uc.execute(RevokeRemediationEntryCommand(workspace_id=_WS, entry_id=entry.id, actor_user_id="intruder"))

        # Fail-closed: still in the corpus AND still embedded.
        assert store.get(entry.id, workspace_id=_WS) is not None
        assert corpus.chunks  # embedding untouched

    def test_owner_admin_authorizes(self):
        store, corpus = FakeStore(), _InMemoryCorpus()
        entry = _entry()
        store.save(entry)
        uc = _build(store=store, corpus=corpus, governance_allowed=True)
        result = uc.execute(RevokeRemediationEntryCommand(workspace_id=_WS, entry_id=entry.id, actor_user_id="owner"))
        assert result is not None

    def test_sign_off_approval_authorizes_even_without_owner_admin(self):
        store, corpus = FakeStore(), _InMemoryCorpus()
        entry = _entry()
        store.save(entry)
        uc = _build(store=store, corpus=corpus, governance_allowed=False, approved=True)
        result = uc.execute(
            RevokeRemediationEntryCommand(
                workspace_id=_WS,
                entry_id=entry.id,
                actor_user_id="reviewer",
                sign_off_artifact_type="remediation_revocation",
                sign_off_artifact_id="signoff-9",
            )
        )
        assert result is not None


class TestRevocationRemovesFromBothStores:
    def test_revoke_drops_the_entry_from_retrieval(self):
        store, corpus = FakeStore(), _InMemoryCorpus()
        entry = _entry()
        store.save(entry)
        EmbedRemediationEntryUseCase(index=corpus).execute(entry)

        retrieval = PgVectorRemediationRetrievalAdapter(store=corpus)
        # Before: retrievable.
        before = retrieval.retrieve_grounding(
            workspace_id=str(_WS), finding_kind="log_watch", query_text="import error"
        )
        assert len(before) == 1

        _build(store=store, corpus=corpus).execute(
            RevokeRemediationEntryCommand(workspace_id=_WS, entry_id=entry.id, actor_user_id="owner", reason="insecure")
        )

        # After: gone from the corpus row (soft-deleted) AND the embedding.
        assert store.get(entry.id, workspace_id=_WS) is None
        after = retrieval.retrieve_grounding(workspace_id=str(_WS), finding_kind="log_watch", query_text="import error")
        assert after == []  # revoked ⇒ never surfaced again

    def test_revocation_is_audited(self):
        store, corpus, audit = FakeStore(), _InMemoryCorpus(), _RecordingAudit()
        entry = _entry()
        store.save(entry)
        _build(store=store, corpus=corpus, audit=audit).execute(
            RevokeRemediationEntryCommand(workspace_id=_WS, entry_id=entry.id, actor_user_id="owner", reason="bad fix")
        )
        assert len(audit.calls) == 1
        assert audit.calls[0]["entry_id"] == entry.id
        assert audit.calls[0]["reason"] == "bad fix"


class TestTenantScope:
    def test_foreign_id_revokes_nothing(self):
        store, corpus = FakeStore(), _InMemoryCorpus()
        entry = _entry()
        store.save(entry)
        # Same entry id but a DIFFERENT workspace → no-op, corpus untouched.
        result = _build(store=store, corpus=corpus).execute(
            RevokeRemediationEntryCommand(workspace_id=uuid4(), entry_id=entry.id, actor_user_id="owner")
        )
        assert result is None
        assert store.get(entry.id, workspace_id=_WS) is not None
