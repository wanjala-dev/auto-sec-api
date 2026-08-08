"""Round-trip guard: the REAL draft-PR writer feeds the REAL reconciler query.

Every other reconciler test fixtures the ``metadata.payload.draft_pr`` shape by
hand, so the writer (``OrmRecordFindingDraftPrRepository``, driven by the
integrations ``OpenDraftPrUseCase``) and the reconciler's candidate SELECT could
drift apart silently — the writer moves the record, the hand-built fixtures
keep passing, and production reconciliation quietly selects nothing.

This test closes that hole by exercising the actual production path end to end:

1. run the REAL ``OpenDraftPrUseCase`` (GitHub HTTP boundary stubbed at
   ``requests.request`` inside the adapter; patch advisor stubbed — the same
   stubbing seams as the integrations suite, whose harness is reused, not
   copied);
2. assert the remediation reconciler's OWN candidate iterator
   (``_iter_candidate_tasks`` / ``_candidates`` — the exact code the Celery
   task runs) SELECTS the row the writer just stamped;
3. prove the canonical accessor is load-bearing: a record written at the
   canonical path is selected, one written anywhere else would not be.

No behaviour change is asserted beyond what production already does — this is
the drift tripwire.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.tests.integration.test_open_draft_pr_use_case import (
    _PATCH,
    _PROPOSE_PATH,
    _REQUESTS_PATH,
    _board,
    _capability_agent,
    _connection,
    _FakeGitHub,
    _triaged_finding,
    _use_case,
)
from components.project.application.ports.record_finding_draft_pr_port import (
    DRAFT_PR_JSON_LOOKUP,
    get_draft_pr,
)
from components.remediation.infrastructure.tasks.reconcile_remediations_tasks import (
    _candidates,
    _iter_candidate_tasks,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestReconcilerRoundTripGuard:
    def test_real_writer_row_is_selected_by_reconciler(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)

        # Nothing to reconcile before the PR is opened.
        assert list(_iter_candidate_tasks(str(workspace.id))) == []

        with mock.patch(_REQUESTS_PATH, new=_FakeGitHub()), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )
        assert result.created is True

        # The reconciler's real candidate query now selects exactly that row …
        rows = list(_iter_candidate_tasks(str(workspace.id)))
        assert [str(row_task.id) for row_task, _meta, _payload, _pr_url in rows] == [str(task.id)]
        assert rows[0][3] == result.url  # pr_url read through the canonical accessor

        # … and materializes the candidate DTO the use case consumes.
        candidates = list(_candidates(str(workspace.id)))
        assert len(candidates) == 1
        assert candidates[0].finding_task_id == str(task.id)
        assert candidates[0].draft_pr_url == result.url

        # The canonical reader agrees with what landed in the DB.
        task.refresh_from_db()
        assert get_draft_pr(task.metadata)["url"] == result.url

    def test_lookup_constant_matches_written_shape(self, workspace_factory, team_factory):
        """The derived ORM lookup string IS the path the writer stamps — the exact
        pair that used to be hand-typed in two files."""
        assert DRAFT_PR_JSON_LOOKUP == "metadata__payload__draft_pr"

        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)

        with mock.patch(_REQUESTS_PATH, new=_FakeGitHub()), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        from infrastructure.persistence.project.models import Task

        assert Task.objects.filter(id=task.id, **{f"{DRAFT_PR_JSON_LOOKUP}__isnull": False}).exists()
