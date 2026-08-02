"""Structural idempotency of the corpus writer (ADR 0012, review item 2).

The "one entry per fix" guarantee is enforced by a PARTIAL UNIQUE CONSTRAINT
(`uniq_active_remediation_per_finding`) — the DB, not a check-then-save window, is
the source of truth. These tests prove:

- a concurrent second insert for the same (workspace, finding_task_id) is caught as
  an idempotent no-op (the existing row is returned; the count stays 1), NOT raised;
- the constraint is PARTIAL: it only binds ACTIVE rows, so revoking an entry frees
  the slot and the same finding can be re-captured (a fresh active row is allowed).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.infrastructure.repositories.remediation_entry_repository import (
    DjangoRemediationEntryRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _entity(workspace, *, finding_task_id="101", entry_id=None) -> RemediationEntry:
    return RemediationEntry(
        id=entry_id or uuid4(),
        workspace_id=workspace.id,
        finding_kind="log_watch",
        source_type="ai.log_watch",
        tags=(),
        language="python",
        code="raw fix",
        title="Fix casing import",
        summary="",
        finding_task_id=finding_task_id,
        finding_fingerprint="fp-abc",
        provenance_event_ref="agent:triage@t1",
        applied_pr_url="https://github.com/acme/repo/pull/7",
        approved_by="signoff-1",
        resolved_at=datetime.now(UTC),
    )


class TestConcurrentInsertIsIdempotent:
    def test_second_insert_same_finding_returns_existing_no_dup(self, workspace_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws = workspace_factory()
        store = DjangoRemediationEntryRepository()

        first = store.save(_entity(ws, finding_task_id="101"))
        # A DIFFERENT entry id but the SAME (workspace, finding_task_id) — the
        # concurrent-insert race. The partial unique constraint fires; the repo
        # catches the IntegrityError and returns the existing row.
        second = store.save(_entity(ws, finding_task_id="101"))

        assert second.id == first.id  # idempotent hit — the existing entry
        assert Row.active.filter(workspace_id=ws.id, finding_task_id="101").count() == 1

    def test_distinct_findings_are_not_collapsed(self, workspace_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws = workspace_factory()
        store = DjangoRemediationEntryRepository()
        store.save(_entity(ws, finding_task_id="101"))
        store.save(_entity(ws, finding_task_id="202"))
        assert Row.active.filter(workspace_id=ws.id).count() == 2


class TestConstraintIsPartial:
    def test_revoke_then_recapture_same_finding_is_allowed(self, workspace_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws = workspace_factory()
        store = DjangoRemediationEntryRepository()

        first = store.save(_entity(ws, finding_task_id="101"))
        store.save(first.revoked())  # soft-delete → frees the active slot

        # A fresh active entry for the SAME finding is now permitted (the constraint
        # only binds non-deleted rows) — revocation + re-capture must stay possible.
        second = store.save(_entity(ws, finding_task_id="101"))

        assert second.id != first.id
        assert Row.active.filter(workspace_id=ws.id, finding_task_id="101").count() == 1
        assert Row.objects.filter(workspace_id=ws.id, finding_task_id="101").count() == 2  # audit rows survive
