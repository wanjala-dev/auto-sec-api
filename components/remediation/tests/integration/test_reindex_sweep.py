"""Integration tests — the re-index sweep re-embeds orphaned/stale vetted fixes (ADR 0012 P6).

Closes the P4b orphan gap: an entry that cleared the D1 gate but whose after-commit
embed never completed (an embeddings-backend outage / lost dispatch) is
admitted-but-unretrievable (``embedded_at IS NULL``). The periodic sweep re-embeds
exactly those (and rating-stale ones), reusing the idempotent per-entry embed task —
and ``mark_embedded`` is the stamp that tells an embedded entry from an orphan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from components.remediation.infrastructure.repositories.remediation_entry_repository import (
    DjangoRemediationEntryRepository,
)

pytestmark = pytest.mark.django_db

_EMBED_TASK = "components.remediation.infrastructure.tasks.embed_remediation_entry_tasks.embed_remediation_entry"


def _row(workspace, *, embedded_at=None, last_outcome_at=None, finding_task_id="task-x"):
    from infrastructure.persistence.remediation.models import RemediationEntry as Row

    return Row.objects.create(
        workspace=workspace,
        finding_kind="log_watch",
        source_type="ai.log_watch",
        code="alias = Real\n",
        finding_task_id=finding_task_id,
        applied_pr_url="https://github.com/org/repo/pull/1",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
        embedded_at=embedded_at,
        last_outcome_at=last_outcome_at,
    )


def test_sweep_reembeds_only_orphaned_and_stale_entries(workspace_factory):
    from components.remediation.infrastructure.tasks.reconcile_remediations_tasks import (
        reindex_remediation_corpus,
    )

    workspace = workspace_factory()
    now = datetime.now(UTC)

    orphan = _row(workspace, embedded_at=None, finding_task_id="orphan")  # never embedded
    stale = _row(  # embedded, but a later outcome makes its rating stale
        workspace, embedded_at=now - timedelta(hours=2), last_outcome_at=now, finding_task_id="stale"
    )
    _row(  # healthy: embedded after its last outcome — NOT a candidate
        workspace, embedded_at=now, last_outcome_at=now - timedelta(hours=2), finding_task_id="healthy"
    )

    with mock.patch(_EMBED_TASK) as embed_task:
        summary = reindex_remediation_corpus(workspace_id=str(workspace.id))

    assert summary["dispatched"] == 2
    dispatched_ids = {c.kwargs["kwargs"]["entry_id"] for c in embed_task.apply_async.call_args_list}
    assert dispatched_ids == {str(orphan.id), str(stale.id)}


def test_mark_embedded_stamps_the_entry(workspace_factory):
    workspace = workspace_factory()
    row = _row(workspace, embedded_at=None)
    assert row.embedded_at is None

    DjangoRemediationEntryRepository().mark_embedded(entry_id=row.id, workspace_id=row.workspace_id)

    row.refresh_from_db()
    assert row.embedded_at is not None


def test_mark_embedded_is_workspace_scoped(workspace_factory):
    ws_a = workspace_factory()
    ws_b = workspace_factory()
    row = _row(ws_a, embedded_at=None)

    # A foreign workspace id stamps nothing (D4).
    DjangoRemediationEntryRepository().mark_embedded(entry_id=row.id, workspace_id=ws_b.id)
    row.refresh_from_db()
    assert row.embedded_at is None
