"""A wrong-SHAPE fix must not ship as verified — end to end (ADR 0019 D5).

The unit tests prove the regexes catch the known-wrong patches. These prove the
gate is actually WIRED: that a wrong-shape patch travelling the real triage
choreography gets sent back for the one re-advise, and that what lands on the card
tells the truth about which happened.

Why this needs its own integration test rather than trusting the unit layer: the
gate depends on the choreography passing the PROPOSED patch (``fix_after``) and not
the grounding text (which contains the offending line and would match every
anti-pattern). That plumbing is exactly the kind of thing that silently regresses
to "always verified" or "never verified", and neither failure is visible without
running the loop.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import code_security_agent as tools
from components.code_security.application.sast_fix_advisor_service import SastFixSuggestion
from infrastructure.persistence.project.models import Column, Task

_SOURCE = "ai.code_security"
_SUGGEST = "components.code_security.application.sast_fix_advisor_service.SastFixAdvisor.suggest"

# The patch that actually shipped in PR #866: grounded, in scope, parses — and binds
# a schema IDENTIFIER as a query parameter, so Postgres raises at runtime.
_WRONG = SastFixSuggestion(
    likely_cause="migrate_schema.py interpolates the schema name into raw SQL (sql-execute-format).",
    suggested_fix="Use parameterised queries in migrate_schema.py instead of an f-string.",
    confidence="high",
    fix_before='cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")',
    fix_after='cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))',
)

# The same finding, fixed correctly: identifiers are composed, not bound.
_RIGHT = SastFixSuggestion(
    likely_cause="migrate_schema.py interpolates the schema name into raw SQL (sql-execute-format).",
    suggested_fix="Compose the identifier with psycopg sql.Identifier in migrate_schema.py.",
    confidence="high",
    fix_before='cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")',
    fix_after='cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))',
)


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _finding(workspace, owner, team, column):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: sql-execute-format — api/scripts/migrate_schema.py:42",
        source_type=_SOURCE,
        metadata={
            "agent_type": "code_security_agent",
            "payload": {
                "rule_id": "autosec.python.sql-execute-format",
                "repo": "wanjala-dev/api-v0.2.0",
                "path": "api/scripts/migrate_schema.py",
                "start_line": 42,
                "end_line": 42,
                "snippet": 'cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")',
                "message": "Raw SQL built with an f-string",
                "severity": "high",
                "language": "python",
                "triage": {"status": "pending"},
            },
        },
    )


@pytest.mark.django_db
class TestFixShapeGate:
    def _agent(self, workspace, owner):
        return SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))

    def test_wrong_shape_is_sent_back_and_the_corrected_fix_ships_verified(self, workspace_factory, team_factory):
        """The happy path of the gate: caught, re-advised, correct fix lands verified."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        with mock.patch(_SUGGEST, side_effect=[_WRONG, _RIGHT]) as advisor:
            tools.triage_code_finding(self._agent(workspace, owner), str(task.id))

        assert advisor.call_count == 2, "the wrong-shape patch must trigger the one re-advise"
        # The re-advise carries the REASON, so the model is told what was wrong.
        feedback = advisor.call_args_list[1].kwargs.get("feedback", "")
        assert "parameterise-values-quote-identifiers" in feedback
        assert "identifier" in feedback.lower()

        task.refresh_from_db()
        payload = task.metadata["payload"]
        assert payload["fix_after"] == _RIGHT.fix_after
        assert payload["verification"] == "verified"
        assert task.metadata["triage"]["needs_human"] is False

    def test_a_wrong_shape_that_survives_the_retry_ships_labeled_not_hidden(self, workspace_factory, team_factory):
        """Label downgrades, artifact still ships — the standing rule (#293)."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        with mock.patch(_SUGGEST, side_effect=[_WRONG, _WRONG]):
            tools.triage_code_finding(self._agent(workspace, owner), str(task.id))

        task.refresh_from_db()
        payload = task.metadata["payload"]
        # The fix is NOT withheld…
        assert payload["fix_after"] == _WRONG.fix_after
        assert payload["suggested_fix"]
        # …but it is labeled, with the named reason an operator can act on.
        assert payload["verification"] == "unverified"
        assert "parameterise-values-quote-identifiers" in task.metadata["triage"]["verification_gap"]

    def test_a_correct_fix_is_never_sent_back(self, workspace_factory, team_factory):
        """The costly false positive: the gate must not re-advise good fixes."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        with mock.patch(_SUGGEST, side_effect=[_RIGHT]) as advisor:
            tools.triage_code_finding(self._agent(workspace, owner), str(task.id))

        assert advisor.call_count == 1, "a correct fix must cost exactly one advisor call"
        task.refresh_from_db()
        assert task.metadata["payload"]["verification"] == "verified"

    def test_the_offending_line_alone_never_trips_the_gate(self, workspace_factory, team_factory):
        """Regression guard for the trap this design exists to avoid.

        The grounding text includes ``fix_before`` — the vulnerable line. If the gate
        ever graded that instead of ``fix_after``, EVERY fix would be rejected. This
        fix's `before` is the wrong shape and its `after` is correct; it must pass.
        """
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _finding(workspace, owner, team, column)

        assert "CREATE SCHEMA IF NOT EXISTS" in _RIGHT.fix_before  # the trap is present
        with mock.patch(_SUGGEST, side_effect=[_RIGHT]) as advisor:
            tools.triage_code_finding(self._agent(workspace, owner), str(task.id))

        assert advisor.call_count == 1
        task.refresh_from_db()
        assert task.metadata["payload"]["verification"] == "verified"
