"""Cloud attack-path triage — the triage_agent's ai.cloud_exposure capability (ADR 0005 phase 3).

Mirrors the log-finding pipeline tests but for attack-path findings: the deterministic
AttackPathRemediationAdvisor recommends how to break the toxic chain (naming the entry +
target → inherently grounded), then the SHARED process_pending_finding core comments,
moves the card to Triage, and stamps it — verified by the same finding_verifier loop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import triage_agent as triage_tools
from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion
from components.cloud_graph.domain.services.attack_path_remediation_advisor import (
    AttackPathRemediationAdvisor,
)
from infrastructure.persistence.project.models import Column, Task, TaskComment

_CLOUD_SOURCE = "ai.cloud_exposure"


class TestAttackPathRemediationAdvisor:
    pytestmark = pytest.mark.unit

    def test_admin_path_names_both_ends_and_is_high_confidence(self):
        s = AttackPathRemediationAdvisor().suggest(
            category="public_compute_admin", entry_label="web-frontend", target_label="AdministratorAccess"
        )
        blob = f"{s.likely_cause} {s.suggested_fix}".lower()
        assert "web-frontend" in blob and "administratoraccess" in blob
        assert s.confidence == "high"

    def test_data_path_addresses_the_bucket(self):
        s = AttackPathRemediationAdvisor().suggest(
            category="public_data_exposure", entry_label="web-frontend", target_label="customer-data"
        )
        assert "customer-data" in s.suggested_fix
        assert s.confidence == "high"

    def test_feedback_is_threaded_into_the_fix(self):
        s = AttackPathRemediationAdvisor().suggest(
            category="public_compute_admin",
            entry_label="web-frontend",
            target_label="AdministratorAccess",
            feedback="be more specific",
        )
        assert "web-frontend → AdministratorAccess" in s.suggested_fix


class TestFindingVerifierCloudExposure:
    pytestmark = pytest.mark.unit

    _PAYLOAD = {"entry": "web-frontend", "target": "AdministratorAccess"}

    def test_grounded_when_suggestion_names_the_path(self):
        r = verify_suggestion(
            source_type=_CLOUD_SOURCE,
            payload=self._PAYLOAD,
            suggestion_text="Detach the AdministratorAccess policy from the role web-frontend can assume.",
        )
        assert r.grounded is True

    def test_ungrounded_when_generic_boilerplate(self):
        r = verify_suggestion(
            source_type=_CLOUD_SOURCE,
            payload=self._PAYLOAD,
            suggestion_text="Follow least-privilege best practices and restrict access.",
        )
        assert r.grounded is False
        assert "attack path" in r.reason

    def test_passes_when_no_checkable_specifics(self):
        r = verify_suggestion(source_type=_CLOUD_SOURCE, payload={}, suggestion_text="anything")
        assert r.grounded is True


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    intake = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, intake


def _agent(workspace, owner):
    return SimpleNamespace(workspace_id=str(workspace.id), user_id=str(owner.id))


def _cloud_task(workspace, owner, team, column):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="Critical: Public aws_ec2_instance 'web-frontend' can reach AdministratorAccess",
        source_type=_CLOUD_SOURCE,
        metadata={
            "agent_type": "triage_agent",
            "provenance": {
                "created_by_kind": "detector",
                "assigned_specialist": "triage_agent",
                "created_at": "2026-07-26T00:00:00+00:00",
                "events": [{"actor": "detector:cloud_graph.attack_paths", "action": "filed finding", "at": "t0"}],
            },
            "payload": {
                "lookup_key": "attack_path:11111111-1111-5111-8111-111111111111",
                "signal": "Public aws_ec2_instance 'web-frontend' can reach AdministratorAccess",
                "confidence": "high",
                "severity": "critical",
                "category": "public_compute_admin",
                "risk_score": 95.0,
                "entry": "web-frontend",
                "target": "AdministratorAccess",
                "evidence": [
                    "web-frontend → app-exec-role → AdministratorAccess",
                    "web-frontend -[can_assume]-> app-exec-role",
                    "app-exec-role -[has_policy]-> AdministratorAccess",
                ],
                "triage": {"status": "pending"},
            },
        },
    )


@pytest.mark.django_db
class TestCloudExposureTriagePipeline:
    def test_triages_the_attack_path_finding_grounded(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cloud_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        result = triage_tools.triage_cloud_exposure(agent, str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        meta = task.metadata
        assert task.column.title == "In Progress"
        assert meta["triage"]["status"] == "triaged"
        assert meta["triage"]["agent"] == "triage_agent"
        assert meta["triage"].get("needs_human") is not True  # grounded → not flagged
        # the remediation is grounded — it names both ends of the path
        fix = meta["payload"]["suggested_fix"].lower()
        assert "web-frontend" in fix and "administratoraccess" in fix
        assert meta["payload"]["confidence"] == "high"
        comment = TaskComment.objects.filter(task=task).first()
        assert comment is not None and "break it" in comment.comment.lower()

    def test_second_run_is_concurrency_safe_noop(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cloud_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        triage_tools.triage_cloud_exposure(agent, str(task.id))
        second = triage_tools.triage_cloud_exposure(agent, str(task.id))

        assert "already handled" in second.lower()
        assert TaskComment.objects.filter(task=task).count() == 1  # no duplicate

    def test_list_pending_surfaces_the_finding(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        _cloud_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        listing = triage_tools.list_pending_cloud_exposure_findings(agent)
        assert "web-frontend" in listing and "public_compute_admin" in listing
