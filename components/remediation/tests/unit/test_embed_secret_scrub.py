"""Unit tests — embed SECRET-SCRUBS the fix code before it lands in the corpus (ADR 0012 P6).

Defence-in-depth: a live secret in a vetted fix must never reach the retrievable
corpus (the advisor reads it back as grounding). The embed use case redacts obvious
credentials from the code BEFORE it becomes chunk content/metadata — and never logs
the raw or matched value (logging.md §4).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
    EmbedRemediationEntryUseCase,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry

pytestmark = pytest.mark.unit

_SECRET = "AKIAIOSFODNN7EXAMPLE"


class _FakeIndex:
    def __init__(self) -> None:
        self.indexed: list[dict] = []

    def index_chunk(self, *, document_key: str, content: str, metadata: dict) -> int:
        self.indexed.append({"document_key": document_key, "content": content, "metadata": metadata})
        return 1

    def delete_by_key(self, *, document_key: str) -> int:  # pragma: no cover - unused
        return 0


def _entry(code: str) -> RemediationEntry:
    return RemediationEntry(
        id=uuid4(),
        workspace_id=uuid4(),
        finding_kind="log_watch",
        source_type="ai.log_watch",
        tags=(),
        language="python",
        code=code,
        title="Fix",
        summary="Summary",
        finding_task_id="task-1",
        finding_fingerprint="fp-1",
        provenance_event_ref="prov-1",
        applied_pr_url="https://github.com/org/repo/pull/1",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
    )


def test_planted_secret_is_redacted_before_embedding():
    entry = _entry(code=f"client = boto3.client('s3', aws_access_key_id='{_SECRET}')\n")
    index = _FakeIndex()

    EmbedRemediationEntryUseCase(index=index).execute(entry)

    call = index.indexed[0]
    # The secret is in neither the searchable content nor the carried metadata code.
    assert _SECRET not in call["content"]
    assert _SECRET not in call["metadata"]["code"]
    assert "«REDACTED-SECRET»" in call["metadata"]["code"]


def test_scrub_never_logs_the_secret(caplog):
    entry = _entry(code=f"api_key = 'sk-{'a' * 24}'\n")
    with caplog.at_level(logging.DEBUG, logger="components.remediation"):
        EmbedRemediationEntryUseCase(index=_FakeIndex()).execute(entry)
    # A redaction happened (warned with a COUNT), but the value never appears in logs.
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "sk-aaaaaaaa" not in joined
    assert "redactions=" in joined


def test_benign_code_passes_through_unscrubbed():
    entry = _entry(code="def add(a, b):\n    return a + b\n")
    index = _FakeIndex()
    EmbedRemediationEntryUseCase(index=index).execute(entry)
    assert "«REDACTED-SECRET»" not in index.indexed[0]["metadata"]["code"]
    assert "return a + b" in index.indexed[0]["metadata"]["code"]
