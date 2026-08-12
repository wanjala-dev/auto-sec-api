"""A SAST card reaches the PR engine with a GRADED patch, or the specialist runs again.

The gap this closes (ADR 0025 Phase 2). Phase 2a made the draft-PR engine ship the
``fix_before`` -> ``fix_after`` the specialist's deep run produced and the rubric
pass validated, falling back to an ungraded advisor only when no snippet applies.
That left one way for ungraded code to reach a customer's repository: a card
carrying *prose* advice but no snippet satisfied the re-run gate, skipped the
graded pass entirely, and landed straight in the fallback.

The gate asked "is there a suggestion?" when the engine needs "is there a patch?".
Prose is not a patch. For SAST the gate now asks for the artifact the engine
actually ships, so the deep run — with RubricMiddleware, the oracles, the DeepRun
record and the repo-read tools — gets a second chance to author one before any
ungraded path is considered.

Non-SAST sources are untouched: they have no ``fix_before``/``fix_after`` contract,
so holding them to one would re-run every log-watch card forever.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.shared_kernel.domain.triage import SOURCE_CODE_SECURITY, SOURCE_LOG_WATCH
from infrastructure.persistence.project.models import Column, Task

_DELEGATE = "components.agents.application.services.detector_cycle._delegate_to_agent"
_OPEN_PR = "components.agents.infrastructure.tasks.agent_tasks._open_draft_pr_for_finding"
_PROVENANCE = "components.agents.infrastructure.tasks.agent_tasks._append_finding_provenance"

pytestmark = pytest.mark.django_db


def _card(
    workspace, owner, team, column, *, source_type=SOURCE_CODE_SECURITY, payload=None, agent="code_security_agent"
):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: sql-execute-format",
        source_type=source_type,
        metadata={
            "agent_type": agent,
            "triage": {"status": "triaged", "suggested": True},
            "payload": payload or {},
        },
    )


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _run(task):
    from components.agents.infrastructure.tasks.agent_tasks import draft_fix_for_finding

    with (
        mock.patch(_DELEGATE, return_value={"thread_id": "run-1"}) as delegate,
        mock.patch(_OPEN_PR, return_value={"pr_url": "https://github.com/x/y/pull/1"}),
        mock.patch(_PROVENANCE),
        mock.patch("components.agents.infrastructure.services.finding_dispatch_service.stamp_dispatch_in_flight"),
    ):
        result = draft_fix_for_finding(
            workspace_id=str(task.workspace_id),
            task_id=str(task.id),
            performed_by=str(task.created_by_id),
        )
    return result, delegate


class TestSastGateRequiresAGradedPatch:
    def test_prose_without_a_snippet_re_runs_the_specialist(self, workspace_factory, team_factory):
        """THE REGRESSION. This card looks handled — triaged, suggested, advice
        text — but carries nothing the PR engine can replay. Before this change it
        sailed past the gate into the ungraded advisor."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        card = _card(
            workspace,
            owner,
            team,
            column,
            payload={"suggested_fix": "Parameterise the table identifier.", "fix_before": "", "fix_after": ""},
        )

        _result, delegate = _run(card)

        assert delegate.call_count == 1

    def test_a_graded_snippet_is_accepted_without_re_running(self, workspace_factory, team_factory):
        """The other half: a card that already carries the graded patch must NOT
        pay for a second deep run. A gate that always re-runs is just as wrong."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        card = _card(
            workspace,
            owner,
            team,
            column,
            payload={
                "suggested_fix": "Parameterise the table identifier.",
                "fix_before": 'cursor.execute("DROP TABLE %s" % table)',
                "fix_after": 'cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))',
            },
        )

        _result, delegate = _run(card)

        delegate.assert_not_called()

    def test_half_a_snippet_is_not_a_patch(self, workspace_factory, team_factory):
        """``fix_after`` with no ``fix_before`` names no location to replace, so the
        replay can never apply it. Treating it as "has a patch" would send the card
        to the fallback with no second graded attempt."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        card = _card(
            workspace,
            owner,
            team,
            column,
            payload={"suggested_fix": "Fix it.", "fix_before": "", "fix_after": "safe_call()"},
        )

        _result, delegate = _run(card)

        assert delegate.call_count == 1


class TestOtherSourcesAreUnaffected:
    def test_log_watch_still_gates_on_the_suggestion_alone(self, workspace_factory, team_factory):
        """Log-watch cards have no fix_before/fix_after contract. Holding them to
        the SAST rule would re-run the specialist on every card, every time."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        card = _card(
            workspace,
            owner,
            team,
            column,
            source_type=SOURCE_LOG_WATCH,
            agent="triage_agent",
            payload={"suggested_fix": "Add a null check before the deref."},
        )

        _result, delegate = _run(card)

        delegate.assert_not_called()
