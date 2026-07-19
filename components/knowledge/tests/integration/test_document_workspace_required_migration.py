"""Tests for the 0013_document_workspace_required migration's guard.

The schema flip itself is mechanical — Django's ``AlterField`` does
the work. The interesting part is the ``guard_no_orphan_documents``
RunPython step: if any orphan ``Document.workspace_id IS NULL`` row
exists at migration time, the guard must raise loudly with an
actionable message rather than letting the constraint add crash
with a vague Postgres NOT NULL violation.

Pre-condition (verified on prod 2026-06-11 via the
``audit_orphan_documents --dry-run`` command) is **zero orphans**.
But a regression — say, the upload endpoint silently dropping
``workspace_id`` again — could land between the audit and the
migration. The guard turns that into a clear "run the audit first"
error rather than a half-applied schema state.

Because the migration is already applied by the time the test DB
is built, the real ``Document`` model has ``workspace_id NOT NULL``
at the SQLite level — so we can't insert an orphan row to exercise
the guard against the real schema. Test by injecting a fake
``apps.get_model`` that returns a stub model whose
``objects.filter(workspace__isnull=True).count()`` returns whatever
the test wants. Same shape Django's own internal migration tests
use when asserting against arbitrary row counts.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from infrastructure.persistence.ai._migration_guards import (
    guard_no_orphan_documents,
    guard_noop_reverse,
)


def _fake_apps_with_orphan_count(count: int):
    """Build a fake ``apps`` whose ``get_model("ai", "Document")``
    returns a model whose orphan-count query resolves to ``count``."""
    fake_model = MagicMock()
    fake_qs = MagicMock()
    fake_qs.count.return_value = count
    fake_model.objects.filter.return_value = fake_qs

    fake_apps = MagicMock()

    def _get_model(app_label, model_name):
        assert (app_label, model_name) == ("ai", "Document"), (
            f"Guard asked for unexpected model: ({app_label}, {model_name})"
        )
        return fake_model

    fake_apps.get_model.side_effect = _get_model
    return fake_apps, fake_model


class TestGuardNoOrphanDocuments:
    def test_zero_orphans_passes(self):
        """Clean DB = guard returns silently. This is the prod
        precondition verified by ``audit_orphan_documents
        --dry-run`` before the migration is applied."""
        fake_apps, fake_model = _fake_apps_with_orphan_count(0)

        guard_no_orphan_documents(fake_apps, schema_editor=None)

        # And the guard actually asked the right question.
        fake_model.objects.filter.assert_called_once_with(
            workspace__isnull=True
        )

    def test_one_orphan_raises_with_runbook_message(self):
        """1+ orphans = the guard raises a clear error naming the
        audit command. A vague "constraint violation" from
        Postgres would force the operator to dig — this message
        tells them what to run."""
        fake_apps, _ = _fake_apps_with_orphan_count(1)

        with pytest.raises(RuntimeError) as exc_info:
            guard_no_orphan_documents(fake_apps, schema_editor=None)

        msg = str(exc_info.value)
        assert "1 Document row" in msg
        assert "audit_orphan_documents --apply" in msg

    def test_seven_orphans_counted_in_message(self):
        """The error tells the operator how many orphans are left
        — useful for sanity-checking against the audit dry-run."""
        fake_apps, _ = _fake_apps_with_orphan_count(7)

        with pytest.raises(RuntimeError) as exc_info:
            guard_no_orphan_documents(fake_apps, schema_editor=None)
        assert "7 Document row" in str(exc_info.value)


class TestGuardNoopReverse:
    def test_returns_silently_for_rollback(self):
        """The reverse direction is a no-op so the migration can
        roll back the schema flip alone without trying to
        un-validate row state."""
        # Should not raise.
        guard_noop_reverse(MagicMock(), schema_editor=None)
