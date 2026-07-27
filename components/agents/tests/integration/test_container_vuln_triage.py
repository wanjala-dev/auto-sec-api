"""Container-CVE triage — the triage_agent's ai.container_security capability (slice 2).

The deterministic ContainerVulnRemediationAdvisor recommends the package upgrade Trivy
already identified (naming the package + fixed version → inherently grounded), then the
SHARED process_pending_finding core comments, moves the card to Triage, and stamps it —
graded by the same finding_verifier loop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import triage_agent as triage_tools
from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion
from components.container_security.domain.services.container_vuln_remediation_advisor import (
    ContainerVulnRemediationAdvisor,
)
from infrastructure.persistence.project.models import Column, Task, TaskComment

_SOURCE = "ai.container_security"


class TestContainerVulnRemediationAdvisor:
    pytestmark = pytest.mark.unit

    def test_fixed_version_names_package_and_target_and_is_high_confidence(self):
        s = ContainerVulnRemediationAdvisor().suggest(
            vulnerability_id="CVE-2024-1234", pkg_name="openssl", installed_version="3.0.11", fixed_version="3.0.14"
        )
        blob = f"{s.likely_cause} {s.suggested_fix}".lower()
        assert "openssl" in blob and "3.0.14" in blob
        assert s.confidence == "high"

    def test_no_fix_available_is_medium_and_advises_mitigation(self):
        s = ContainerVulnRemediationAdvisor().suggest(
            vulnerability_id="CVE-2024-9999", pkg_name="libfoo", installed_version="1.0", fixed_version=""
        )
        assert s.confidence == "medium"
        assert "no fixed version" in s.suggested_fix.lower()


class TestFindingVerifierContainerSecurity:
    pytestmark = pytest.mark.unit

    _PAYLOAD = {"pkg_name": "openssl", "vulnerability_id": "CVE-2024-1234", "fixed_version": "3.0.14"}

    def test_grounded_when_suggestion_names_package_or_fix(self):
        r = verify_suggestion(
            source_type=_SOURCE, payload=self._PAYLOAD, suggestion_text="Upgrade openssl to 3.0.14 and rebuild."
        )
        assert r.grounded is True

    def test_ungrounded_when_generic(self):
        r = verify_suggestion(
            source_type=_SOURCE, payload=self._PAYLOAD, suggestion_text="Keep your dependencies up to date."
        )
        assert r.grounded is False
        assert "CVE" in r.reason


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


def _cve_task(workspace, owner, team, column):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: CVE-2024-1234 in openssl",
        source_type=_SOURCE,
        metadata={
            "agent_type": "triage_agent",
            "provenance": {
                "created_by_kind": "detector",
                "assigned_specialist": "triage_agent",
                "created_at": "2026-07-26T00:00:00+00:00",
                "events": [{"actor": "scanner:container_security.trivy", "action": "filed finding", "at": "t0"}],
            },
            "payload": {
                "lookup_key": "CVE-2024-1234|registry/app:1.0|openssl|3.0.11",
                "signal": "CVE-2024-1234 in openssl",
                "confidence": "high",
                "severity": "high",
                "vulnerability_id": "CVE-2024-1234",
                "pkg_name": "openssl",
                "installed_version": "3.0.11",
                "fixed_version": "3.0.14",
                "primary_url": "https://avd.aquasec.com/nvd/cve-2024-1234",
                "triage": {"status": "pending"},
            },
        },
    )


@pytest.mark.django_db
class TestContainerVulnTriagePipeline:
    def test_triages_the_cve_grounded(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        result = triage_tools.triage_container_vuln(agent, str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        meta = task.metadata
        assert task.column.title == "Triage"
        assert meta["triage"]["status"] == "triaged"
        assert meta["triage"]["agent"] == "triage_agent"
        assert meta["triage"].get("needs_human") is not True  # grounded → not flagged
        fix = meta["payload"]["suggested_fix"].lower()
        assert "openssl" in fix and "3.0.14" in fix
        assert meta["payload"]["confidence"] == "high"
        assert TaskComment.objects.filter(task=task).count() == 1

    def test_second_run_is_concurrency_safe_noop(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        triage_tools.triage_container_vuln(agent, str(task.id))
        second = triage_tools.triage_container_vuln(agent, str(task.id))

        assert "already handled" in second.lower()
        assert TaskComment.objects.filter(task=task).count() == 1

    def test_list_pending_surfaces_the_cve(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        _cve_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)

        listing = triage_tools.list_pending_container_vuln_findings(agent)
        assert "openssl" in listing and "CVE-2024-1234" in listing
