"""The board card's finding envelope must match the finding's REMEDIATION TARGET.

The ``log_watch`` envelope is what the HUD's board card / callout key their
affordances off. A container CVE from a public/unlinked image carries a FIX
SNIPPET and remediation_target="image" — never the draft-PR affordance a repo
finding gets. (Pre-fix, the card offered PREVIEW & OPEN DRAFT PR for container
findings; the engine then refused them as ``finding_not_found`` after a burned
specialist run.)
"""

from __future__ import annotations

import pytest

from components.project.mappers.rest.project_serializers import TaskSerializer
from infrastructure.persistence.project.models import Column, Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _task(workspace, owner, team, column, *, source_type, payload):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="finding",
        source_type=source_type,
        metadata={"agent_type": "triage_agent", "payload": payload},
    )


def test_container_finding_envelope_targets_the_image_with_a_snippet(workspace_factory, team_factory):
    workspace, owner, team, column = _board(workspace_factory, team_factory)
    task = _task(
        workspace,
        owner,
        team,
        column,
        source_type="ai.container_security",
        payload={
            "signal": "CVE-2021-23017 in nginx",
            "vulnerability_id": "CVE-2021-23017",
            "pkg_name": "nginx",
            "target": "nginx:1.16.0 (debian 10.3)",
            "fix_snippet": "# CVE-2021-23017\nFROM nginx:1.16.0   # bump this tag",
            "fix_snippet_language": "dockerfile",
        },
    )

    lw = TaskSerializer(task).data["log_watch"]
    assert lw["remediation_target"] == "image"
    assert "FROM nginx:1.16.0" in lw["fix_snippet"]
    assert lw["fix_snippet_language"] == "dockerfile"


def test_sast_finding_envelope_keeps_the_repo_target(workspace_factory, team_factory):
    workspace, owner, team, column = _board(workspace_factory, team_factory)
    task = _task(
        workspace,
        owner,
        team,
        column,
        source_type="ai.code_security",
        payload={"signal": "sqli", "rule_id": "r", "path": "a.py", "snippet": "x"},
    )

    lw = TaskSerializer(task).data["log_watch"]
    assert lw["remediation_target"] == "repo"
    assert lw["fix_snippet"] == ""
