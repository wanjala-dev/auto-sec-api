"""The measured confidence label must reach the operator (ADR 0032 D11 A).

``code_security_agent`` has computed ``fix_confidence(...).as_label()`` and
written it to ``payload["fix_confidence"]`` since #117 step 3 — a per-rule tier
derived from real eval counts, with a Wilson bound and an expiry, which is
better than anything the reference app or most vendors ship. **No backend
reader rendered it.** The one honest, statistically grounded number in the
product was computed on every SAST triage and thrown away.

The ADR calls making it visible the highest value-per-line change in the whole
document, and it is Tom's literal ask ("trust agent output via golden-dataset
eval + confidence values"). These tests pin it at both surfaces an operator
actually looks at: the board card and the draft PR body.

They also pin the two ways rendering it could become dishonest:
* a bare tier with no counts (a tier without its n is the thing the bound exists
  to prevent), and
* inventing "unproven" for an older finding that carries no label at all —
  never-stamped and measured-and-found-wanting are different facts.
"""

from __future__ import annotations

import pytest

from components.project.mappers.rest.project_serializers import TaskSerializer
from infrastructure.persistence.project.models import Column, Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_LABEL = {
    "tier": "measured_weak",
    "reason": "6/8 correct, but 10 trials are the floor — too few runs to distinguish a good rule from a lucky one",
    "trials": 8,
    "passes": 6,
    "lower_bound": 0.463,
}


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _sast_task(workspace, owner, team, column, *, payload):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="[HIGH] SQL built with string formatting",
        source_type="ai.code_security",
        metadata={"agent_type": "code_security_agent", "payload": payload},
    )


class TestTheBoardCardCarriesTheLabel:
    def test_the_label_reaches_the_card_intact(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_task(
            workspace,
            owner,
            team,
            column,
            payload={
                "rule_id": "autosec.python.sql-execute-format",
                "repo": "acme/api",
                "path": "app/db.py",
                "start_line": 42,
                "fix_confidence": dict(_LABEL),
            },
        )

        label = TaskSerializer(task).data["log_watch"]["fix_confidence"]

        assert label is not None, "computed on every SAST triage and previously discarded"
        assert label["tier"] == "measured_weak"

    def test_the_tier_never_travels_without_its_counts(self, workspace_factory, team_factory):
        """A tier with no n is a claim; a tier with n is a measurement."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_task(workspace, owner, team, column, payload={"rule_id": "r1", "fix_confidence": dict(_LABEL)})

        label = TaskSerializer(task).data["log_watch"]["fix_confidence"]

        assert label["trials"] == 8
        assert label["passes"] == 6
        assert label["lower_bound"] == 0.463
        assert "too few" in label["reason"]

    def test_an_unstamped_finding_renders_absent_not_unproven(self, workspace_factory, team_factory):
        """Never measured and measured-and-weak are different facts (D4)."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_task(workspace, owner, team, column, payload={"rule_id": "r1"})

        assert TaskSerializer(task).data["log_watch"]["fix_confidence"] is None

    def test_non_sast_findings_are_unaffected(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            column=column,
            created_by=owner,
            title="error finding",
            source_type="ai.log_watch",
            metadata={"agent_type": "triage_agent", "payload": {"signal": "ERROR"}},
        )

        assert "fix_confidence" not in TaskSerializer(task).data["log_watch"]


class TestTheDraftPrCarriesTheLabel:
    """The PR reviewer is exactly who the number is for."""

    @staticmethod
    def _section(payload):
        from components.integrations.application.use_cases.open_draft_pr_use_case import (
            OpenDraftPrUseCase,
        )

        return OpenDraftPrUseCase._fix_confidence_section(payload)

    def test_the_pr_body_states_the_tier_with_its_counts_and_bound(self):
        body = self._section({"fix_confidence": dict(_LABEL)})

        assert "Measured confidence for this rule" in body
        assert "measured weak" in body
        assert "6/8 measured" in body
        assert "0.46" in body  # the BOUND, not "75%"

    def test_a_finding_with_no_label_adds_no_section(self):
        assert self._section({}) == ""
        assert self._section({"fix_confidence": None}) == ""
        assert self._section({"fix_confidence": {}}) == ""

    def test_the_section_says_it_labels_and_does_not_gate(self):
        """Standing rule: confidence downgrades the LABEL, never withholds the artifact."""
        body = self._section({"fix_confidence": dict(_LABEL)})
        assert "never a gate" in body
