"""End-to-end outcome tracking + governance revocation over real persistence (P5).

Proves against the DB and the real adapters:
- a second same-class admission RAISES the prior entry's stored score (reuse+success);
- a same-fingerprint recurrence LOWERS the prior entry's stored score;
- revocation soft-deletes the corpus row, deletes its embedding chunk from
  ``ai_embedding_chunks``, and writes a governance audit row — and only a workspace
  owner/admin may do it (the real governance adapter authorizes/denies);
- every write goes through the sole-writer repository.
"""

from __future__ import annotations

import pytest

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.commands.revoke_remediation_entry_command import (
    RevokeRemediationEntryCommand,
)
from components.remediation.application.providers.remediation_provider import (
    build_embed_remediation_entry_use_case,
    build_remediation_service,
)
from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
    document_key_for,
)
from components.remediation.domain.errors import RevocationNotAuthorizedError
from components.remediation.infrastructure.adapters.board_finding_facts_repository import (
    BoardFindingFactsRepository,
)
from components.remediation.infrastructure.repositories.remediation_entry_repository import (
    DjangoRemediationEntryRepository,
)
from components.remediation.tests.unit.fakes import FakeSignOffGate

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_PR = "https://github.com/acme/repo/pull/7"


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])
    column = Column.objects.create(team=team, workspace=ws, project=None, title="Backlog", order=0, created_by=owner)
    return ws, owner, team, column


def _finding(ws, owner, team, column, *, fingerprint):
    from infrastructure.persistence.project.models import Task

    return Task.objects.create(
        team=team,
        workspace=ws,
        column=column,
        created_by=owner,
        title="[FINDING] casing ImportError",
        source_type="ai.log_watch",
        metadata={
            "provenance": {"events": [{"actor": "agent:triage via user:u1", "action": "opened draft PR", "at": "t1"}]},
            "triage": {"status": "resolved"},
            "payload": {"fingerprint": fingerprint, "draft_pr": {"url": _PR, "repo": "acme/repo"}},
        },
    )


def _service(store):
    return build_remediation_service(
        store=store,
        sign_off_gate=FakeSignOffGate(approved=True),
        finding_facts=BoardFindingFactsRepository(),
    )


def _cmd(ws, task, code="fix()"):
    return RecordRemediationEntryCommand(
        workspace_id=ws.id,
        finding_task_id=str(task.id),
        sign_off_artifact_type="remediation",
        sign_off_artifact_id="signoff-1",
        pr_applied=True,
        applied_pr_url=_PR,
        code=code,
        language="python",
        title="Fix",
    )


class TestOutcomeTracking:
    def test_second_same_class_admission_raises_prior_score(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        store = DjangoRemediationEntryRepository()
        service = _service(store)

        first = service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-A")))
        baseline = Row.objects.get(id=first.id).score

        # A second same-kind fix (different fingerprint) merges/resolves → the prior
        # earns reuse+success, so its stored score rises.
        service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-B")))

        first_row = Row.objects.get(id=first.id)
        assert first_row.reuse_count == 1
        assert first_row.success_count == 1
        assert first_row.score > baseline

    def test_recurrence_lowers_prior_score(self, workspace_factory, team_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        store = DjangoRemediationEntryRepository()
        service = _service(store)

        first = service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-SAME")))
        baseline = Row.objects.get(id=first.id).score

        # The SAME finding recurs (same fingerprint, new task) → the prior fix did
        # not hold, so its score drops.
        service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-SAME")))

        first_row = Row.objects.get(id=first.id)
        assert first_row.recurrence_count == 1
        assert first_row.score < baseline


class TestGovernedRevocation:
    def test_owner_revokes_soft_deletes_deletes_embedding_and_audits(self, workspace_factory, team_factory):
        from infrastructure.persistence.ai.models import EmbeddingChunk
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        store = DjangoRemediationEntryRepository()
        service = _service(store)
        entry = service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-1")))

        # Make it retrievable (write its embedding chunk), then revoke.
        build_embed_remediation_entry_use_case().execute(entry)
        key = document_key_for(str(entry.id))
        assert EmbeddingChunk.objects.filter(metadata__document_key=key).count() == 1

        result = service.revoke(
            RevokeRemediationEntryCommand(
                workspace_id=ws.id, entry_id=entry.id, actor_user_id=str(owner.id), reason="found insecure"
            )
        )

        assert result is not None
        # Corpus row soft-deleted (audit row survives), embedding gone.
        assert Row.active.filter(id=entry.id).count() == 0
        assert Row.objects.filter(id=entry.id, is_deleted=True).count() == 1
        assert EmbeddingChunk.objects.filter(metadata__document_key=key).count() == 0
        # Governance action audited.
        from infrastructure.persistence.audit.models import EntityAuditLog

        assert EntityAuditLog.objects.filter(object_id=str(entry.id), field_name="corpus_membership").exists()

    def test_non_owner_is_denied_and_nothing_changes(self, workspace_factory, team_factory, user_factory):
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ws, owner, team, column = _board(workspace_factory, team_factory)
        store = DjangoRemediationEntryRepository()
        service = _service(store)
        entry = service.record(_cmd(ws, _finding(ws, owner, team, column, fingerprint="fp-1")))

        outsider = user_factory()  # not a member/owner of ws
        with pytest.raises(RevocationNotAuthorizedError):
            service.revoke(
                RevokeRemediationEntryCommand(
                    workspace_id=ws.id, entry_id=entry.id, actor_user_id=str(outsider.id), reason="malicious"
                )
            )
        # Still in the retrievable corpus — a poisoning-by-revocation attempt failed.
        assert Row.active.filter(id=entry.id).count() == 1
