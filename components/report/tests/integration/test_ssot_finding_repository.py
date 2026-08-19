"""The report's finding read, against the Finding SSOT with board enrichment.

These lock the behaviour the change exists to produce:

- a **medium** finding reaches a report — and demonstrably did NOT before, because
  the board adapter cannot see it (the board files at ``high``, ADR 0019 D4);
- an SSOT-only source reaches a report (ADR 0021 D4 keeps whole source classes
  off the board deliberately);
- board state joins on as enrichment, and a finding with no card is explicitly
  **untriaged** rather than silently shapeless;
- nothing is dropped in silence: truncation, suppression, resolution and sample
  data are each COUNTED and surfaced.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from components.report.application.ports.finding_source_port import FindingQuery
from components.report.infrastructure.repositories.board_finding_repository import (
    BoardFindingRepository,
)
from components.report.infrastructure.repositories.ssot_finding_repository import (
    SsotFindingRepository,
)
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.django_db]


def _finding(ws, *, severity="high", status="open", source="cloud_posture.prowler", title=None, **overrides):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source=source,
        fingerprint=overrides.pop("fingerprint", f"fp-{uuid.uuid4()}"),
        asset_urn=overrides.pop("asset_urn", f"arn:aws:s3:::bucket-{uuid.uuid4()}"),
        severity=severity,
        status=status,
        title=title or f"{severity.title()} finding",
        description=overrides.pop("description", "Something is misconfigured."),
        remediation=overrides.pop("remediation", "Turn it off."),
        compliance=overrides.pop("compliance", {"CIS-2.0": ["2.1.5"]}),
        first_seen_at=overrides.pop("first_seen_at", now),
        last_seen_at=overrides.pop("last_seen_at", now),
        **overrides,
    )


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner], title="AI Findings")
    column = Column.objects.create(
        team=team, workspace=ws, project=None, title="In Progress", order=0, created_by=owner
    )
    return ws, owner, team, column


def _card(ws, owner, team, column, finding, *, source_type="ai.cloud_posture", assignees=()):
    """The board's local copy of a finding, shaped exactly as
    ``persist_finding_as_task`` writes it (finding id nested under payload)."""
    from infrastructure.persistence.project.models import Task

    task = Task.objects.create(
        team=team,
        workspace=ws,
        column=column,
        created_by=owner,
        title=finding.title,
        source_type=source_type,
        status="todo",
        metadata={
            "severity": finding.severity,
            "triage": {"status": "triaged"},
            "payload": {"finding_id": str(finding.id), "lookup_key": finding.fingerprint},
            "context": {"finding_id": str(finding.id)},
        },
    )
    if assignees:
        task.assigned_to.set(assignees)
    return task


def _read(ws, **kwargs) -> object:
    return SsotFindingRepository().list_findings(FindingQuery(workspace_id=str(ws.id), **kwargs))


class TestTheSeverityFloorNoLongerHidesFindings:
    """The headline: the board's floor made low/medium findings unreportable."""

    def test_medium_finding_reaches_the_report_and_did_not_before(self, workspace_factory, team_factory):
        ws, owner, team, column = _board(workspace_factory, team_factory)
        high = _finding(ws, severity="high", title="Public S3 bucket")
        medium = _finding(ws, severity="medium", title="CloudTrail not multi-region")
        # The board floor files at ``high``: the high gets a card, the medium
        # never does. This is the exact board state the floor produces.
        _card(ws, owner, team, column, high)

        board_page = BoardFindingRepository().list_findings(
            FindingQuery(workspace_id=str(ws.id), source_prefixes=("ai.",))
        )
        board_titles = {f["title"] for f in board_page.findings}
        assert board_titles == {"Public S3 bucket"}, "precondition: the board cannot see the medium"

        page = _read(ws)
        assert {f["title"] for f in page.findings} == {"Public S3 bucket", "CloudTrail not multi-region"}
        assert page.total_matched == 2
        assert page.truncated_count == 0
        found = next(f for f in page.findings if f["id"] == str(medium.id))
        assert found["severity"] == "medium", "severity is first-class on the mapping, not buried in metadata"

    def test_low_and_informational_findings_reach_the_report(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, severity="low", title="GuardDuty off")
        _finding(ws, severity="informational", title="Region has no workloads")

        page = _read(ws)
        assert {f["severity"] for f in page.findings} == {"low", "informational"}

    def test_an_ssot_only_source_reaches_the_report(self, workspace_factory):
        """ADR 0021 D4 keeps domain/DNS hygiene off the board entirely."""
        ws = workspace_factory()
        _finding(ws, source="cloud_posture.prowler.vercel", severity="medium", title="No DNSSEC on apex domain")

        page = _read(ws)
        assert [f["source"] for f in page.findings] == ["cloud_posture.prowler.vercel"]
        assert page.findings[0]["triage"]["on_board"] is False


class TestBoardEnrichment:
    def test_board_state_attaches_to_the_finding(self, workspace_factory, team_factory, user_factory):
        ws, owner, team, column = _board(workspace_factory, team_factory)
        assignee = user_factory(username="rhodes")
        finding = _finding(ws, severity="high")
        _card(ws, owner, team, column, finding, assignees=[assignee])

        triage = _read(ws).findings[0]["triage"]
        assert triage["on_board"] is True
        assert triage["column"] == "In Progress"
        assert triage["team"] == "AI Findings"
        assert triage["triage_status"] == "triaged"
        assert triage["assignees"] == ["rhodes"]
        assert triage["source_type"] == "ai.cloud_posture"

    def test_a_finding_with_no_card_is_explicitly_untriaged(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, severity="high")

        triage = _read(ws).findings[0]["triage"]
        assert triage == {"on_board": False}, "untriaged must be a stated fact, not a missing key"

    def test_a_card_from_another_workspace_never_enriches(self, workspace_factory, team_factory):
        """The join is workspace-scoped — application-enforced isolation is all
        there is in a single-DB deployment."""
        ws, _owner, _team, _column = _board(workspace_factory, team_factory)
        other_ws, other_owner, other_team, other_column = _board(workspace_factory, team_factory)
        finding = _finding(ws, severity="high")
        # A card in ANOTHER workspace naming this workspace's finding id.
        _card(other_ws, other_owner, other_team, other_column, finding)

        assert _read(ws).findings[0]["triage"] == {"on_board": False}

    def test_another_workspaces_findings_are_never_returned(self, workspace_factory):
        ws = workspace_factory()
        other = workspace_factory()
        _finding(ws, title="Mine")
        _finding(other, title="Theirs")

        assert [f["title"] for f in _read(ws).findings] == ["Mine"]


class TestNothingIsDroppedInSilence:
    def test_suppressed_and_resolved_are_excluded_but_counted(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, severity="high", title="Open one")
        _finding(ws, severity="high", title="Accepted risk", status="suppressed")
        _finding(ws, severity="high", title="Fixed", status="resolved", resolved_at=timezone.now())

        page = _read(ws)
        assert [f["title"] for f in page.findings] == ["Open one"]
        assert page.total_matched == 1
        assert page.excluded_suppressed == 1
        assert page.excluded_resolved == 1

    def test_a_kind_that_opts_in_gets_the_terminal_findings(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, severity="high", title="Open one")
        _finding(ws, severity="high", title="Fixed", status="resolved", resolved_at=timezone.now())

        page = _read(ws, include_resolved=True)
        assert {f["title"] for f in page.findings} == {"Open one", "Fixed"}
        assert page.excluded_resolved == 0

    def test_truncation_is_reported_and_keeps_the_most_severe(self, workspace_factory):
        ws = workspace_factory()
        for band in ("low", "low", "critical", "medium", "high"):
            _finding(ws, severity=band, title=f"{band} finding")

        page = _read(ws, limit=2)
        assert page.total_matched == 5
        assert page.returned_count == 2
        assert page.truncated_count == 3
        assert [f["severity"] for f in page.findings] == ["critical", "high"], (
            "a truncated report must keep its criticals and drop its lows, never the reverse"
        )

    def test_sample_findings_are_included_and_flagged(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, source="sample.cloud_posture", severity="critical", title="Demo bucket")
        _finding(ws, source="cloud_posture.prowler", severity="high", title="Real finding")

        page = _read(ws)
        assert page.sample_count == 1
        flags = {f["title"]: f["is_sample"] for f in page.findings}
        assert flags == {"Demo bucket": True, "Real finding": False}

    def test_sample_findings_can_be_excluded_and_are_then_counted(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, source="sample.cloud_posture", severity="critical", title="Demo bucket")
        _finding(ws, source="cloud_posture.prowler", severity="high", title="Real finding")

        page = _read(ws, include_sample=False)
        assert [f["title"] for f in page.findings] == ["Real finding"]
        assert page.excluded_sample == 1
        assert page.sample_count == 0


class TestScopeFilters:
    def test_source_prefix_scoping_selects_a_whole_pillar(self, workspace_factory):
        ws = workspace_factory()
        _finding(ws, source="cloud_posture.prowler", title="AWS")
        _finding(ws, source="cloud_posture.prowler.vercel", title="Vercel")
        _finding(ws, source="container_security.trivy", title="CVE")

        page = _read(ws, source_prefixes=("cloud_posture",))
        assert {f["title"] for f in page.findings} == {"AWS", "Vercel"}

    def test_the_window_keys_off_the_observation_lifecycle(self, workspace_factory):
        """A period report asks what was LIVE in the period — which the board
        card's ``created_at`` could never answer."""
        ws = workspace_factory()
        now = timezone.now()
        old_closed = _finding(
            ws,
            title="Closed before the period",
            status="resolved",
            first_seen_at=now - timedelta(days=90),
            last_seen_at=now - timedelta(days=80),
            resolved_at=now - timedelta(days=80),
        )
        long_running = _finding(
            ws,
            title="Open since before the period",
            first_seen_at=now - timedelta(days=90),
            last_seen_at=now,
        )
        future = _finding(ws, title="First seen after the period", first_seen_at=now, last_seen_at=now)

        page = _read(
            ws,
            since=now - timedelta(days=30),
            until=now - timedelta(days=1),
            include_resolved=True,
        )
        titles = {f["title"] for f in page.findings}
        assert long_running.title in titles, "a finding open THROUGH the period is in the period"
        assert old_closed.title not in titles, "closed before the window opened"
        assert future.title not in titles, "first seen after the window closed"


class TestMappingShape:
    def test_the_mapping_carries_the_ssot_facts_the_report_renders(self, workspace_factory):
        ws = workspace_factory()
        finding = _finding(
            ws,
            severity="critical",
            title="Public S3 bucket",
            asset_urn="arn:aws:s3:::acme-exports",
            remediation="Block public access.",
            compliance={"CIS-2.0": ["2.1.5"], "PCI-DSS": ["1.2"]},
            attributes={"region": "us-east-1", "check_id": "s3_bucket_public_access"},
        )

        row = _read(ws).findings[0]
        assert row["id"] == str(finding.id)
        assert row["dedup_key"] == f"cloud_posture.prowler|{finding.fingerprint}"
        payload = row["metadata"]["payload"]
        assert payload["asset_urn"] == "arn:aws:s3:::acme-exports"
        assert payload["recommendation"] == "Block public access."
        evidence = {(e["type"], e["detail"]) for e in payload["evidence"]}
        assert ("asset", "arn:aws:s3:::acme-exports") in evidence
        assert ("CIS-2.0", "2.1.5") in evidence
        assert ("region", "us-east-1") in evidence

    def test_a_report_summary_card_is_not_readable_back_as_a_finding(self, workspace_factory, team_factory):
        """``ai.posture_report`` needed an explicit exclusion on the board path.

        Reading the SSOT makes it unnecessary: ``PostureReportDetector`` writes a
        board Task directly and never raises a Finding, so a report's own summary
        card simply is not in the SSOT to be read back.
        """
        ws, owner, team, column = _board(workspace_factory, team_factory)
        from infrastructure.persistence.project.models import Task

        Task.objects.create(
            team=team,
            workspace=ws,
            column=column,
            created_by=owner,
            title="Weekly posture report",
            source_type="ai.posture_report",
            metadata={"severity": "high", "payload": {"lookup_key": "posture_report:2026-W33"}},
        )
        _finding(ws, severity="high", title="A real finding")

        assert [f["title"] for f in _read(ws).findings] == ["A real finding"]
