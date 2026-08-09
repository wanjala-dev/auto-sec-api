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


class TestFixSnippetArtifact:
    """The image-target artifact (remediation-target distinction): a container CVE
    with no linked repo cannot carry a draft PR — its artifact is a deterministic
    FIX SNIPPET (Dockerfile/package guidance), anchored to the CVE's own facts."""

    pytestmark = pytest.mark.unit

    def test_debian_image_snippet_carries_from_bump_and_apt_line(self):
        from components.container_security.domain.services.container_vuln_remediation_advisor import (
            build_fix_snippet,
        )

        snippet = build_fix_snippet(
            vulnerability_id="CVE-2021-23017",
            pkg_name="nginx",
            installed_version="1.16.0",
            fixed_version="1.20.1",
            target="nginx:1.16.0 (debian 10.3)",
        )
        assert "CVE-2021-23017" in snippet
        assert "FROM nginx:1.16.0" in snippet  # the base-image line to bump
        assert "apt-get install -y --only-upgrade nginx" in snippet
        assert "1.20.1" in snippet

    def test_alpine_image_uses_apk(self):
        from components.container_security.domain.services.container_vuln_remediation_advisor import (
            build_fix_snippet,
        )

        snippet = build_fix_snippet(
            vulnerability_id="CVE-2024-1234",
            pkg_name="openssl",
            installed_version="3.0.11",
            fixed_version="3.0.14",
            target="node:18-alpine (alpine 3.18)",
        )
        assert "apk upgrade --no-cache openssl" in snippet

    def test_no_fixed_version_is_honest_not_invented(self):
        from components.container_security.domain.services.container_vuln_remediation_advisor import (
            build_fix_snippet,
        )

        snippet = build_fix_snippet(
            vulnerability_id="CVE-2024-9999",
            pkg_name="libfoo",
            installed_version="1.0",
            fixed_version="",
            target="registry/app:1.0 (debian 12)",
        )
        assert "no fixed version published yet" in snippet
        assert "Mitigate" in snippet

    def test_advisor_suggestion_carries_the_snippet(self):
        s = ContainerVulnRemediationAdvisor().suggest(
            vulnerability_id="CVE-2024-1234",
            pkg_name="openssl",
            installed_version="3.0.11",
            fixed_version="3.0.14",
            target="nginx:1.16.0 (debian 10.3)",
        )
        assert "FROM nginx:1.16.0" in s.fix_snippet
        assert s.fix_snippet_language == "dockerfile"


@pytest.mark.django_db
class TestPublicImageRemediationTarget:
    """Named regression — Henry's public-image case: container-scan findings from
    PUBLIC images (nginx/node demo scans, or any image URL a user points a scan
    at) have no repo to draft a PR against. The old behavior burned a specialist
    run and then stamped a misleading "PR BLOCKED: finding not found" on the
    card. Now: the artifact matches the target — a FIX SNIPPET on the finding,
    NO PR attempt, NO draft-PR affordance."""

    def test_triage_stamps_the_fix_snippet_on_the_card(self, workspace_factory, team_factory):
        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)
        # A public-image scan: Trivy's target names the image, no repo anywhere.
        meta = task.metadata
        meta["payload"]["target"] = "nginx:1.16.0 (debian 10.3)"
        task.metadata = meta
        task.save(update_fields=["metadata"])
        agent = _agent(workspace, owner)

        result = triage_tools.triage_container_vuln(agent, str(task.id))

        assert "Handled" in result
        task.refresh_from_db()
        payload = task.metadata["payload"]
        assert "FROM nginx:1.16.0" in payload["fix_snippet"]
        assert payload["fix_snippet_language"] == "dockerfile"
        comment = TaskComment.objects.filter(task=task).first()
        assert "Fix snippet" in comment.comment

    def test_triage_state_offers_snippet_not_pr(self, workspace_factory, team_factory):
        from components.findings.application.queries.finding_triage_state_query import (
            derive_triage_state,
        )

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)
        agent = _agent(workspace, owner)
        triage_tools.triage_container_vuln(agent, str(task.id))
        task.refresh_from_db()

        state = derive_triage_state(
            card={"source_type": _SOURCE, "task_id": str(task.id), "metadata": task.metadata}
        )
        assert state.state == "fix_ready"
        assert state.remediation_target == "image"
        assert state.fix_snippet  # the artifact IS present…
        assert state.can_draft_fix is False  # …and the doomed PR affordance is not

    def test_queued_public_image_finding_never_offers_the_pr_button(self, workspace_factory, team_factory):
        from components.findings.application.queries.finding_triage_state_query import (
            derive_triage_state,
        )

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)

        state = derive_triage_state(
            card={"source_type": _SOURCE, "task_id": str(task.id), "metadata": task.metadata}
        )
        assert state.state == "queued"
        assert state.remediation_target == "image"
        assert state.can_draft_fix is False

    def test_draft_fix_request_is_refused_typed_before_any_run(self, workspace_factory, team_factory):
        """No PR attempt: the request path refuses no_repo_target BEFORE burning a
        specialist run — replacing the doomed run + 'finding not found' noise."""
        from unittest import mock

        from components.agents.application.ports.finding_dispatch_port import DraftFixRefused
        from components.agents.infrastructure.services import finding_dispatch_service as fds

        workspace, owner, team, intake = _board(workspace_factory, team_factory)
        task = _cve_task(workspace, owner, team, intake)

        with (
            mock.patch.object(fds, "_enqueue_draft_fix") as enqueue,
            pytest.raises(DraftFixRefused) as exc,
        ):
            fds.request_draft_fix(str(workspace.id), str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "no_repo_target"
        enqueue.assert_not_called()
        task.refresh_from_db()
        assert "draft_pr_blocked" not in (task.metadata or {})  # no misleading noise

    def test_linked_repo_container_finding_keeps_the_pr_target(self):
        """The future seam: an image traceable to a connected repo build flips to
        the repo target — the distinction is per-finding, not per-source."""
        from components.shared_kernel.domain.triage import remediation_target

        assert remediation_target(_SOURCE, {}) == "image"
        assert remediation_target(_SOURCE, {"repo": "wanjala-dev/auto-sec-api"}) == "repo"
        assert remediation_target("ai.code_security", {}) == "repo"
        assert remediation_target("ai.log_watch", {}) == "repo"
        assert remediation_target("ai.cloud_exposure", {}) == "cloud"
        assert remediation_target("ai.log_optimization", {}) == "service"
        assert remediation_target("ai.cloud_posture", {}) == "none"
