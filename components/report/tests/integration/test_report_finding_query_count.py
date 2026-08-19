"""N+1 regression guard for the report's finding read (perf rule §1).

A report reads EVERY finding in scope and joins each one's board card on for
triage state. Done naively that is one card lookup per finding plus one assignee
lookup per card — an N+1 across the whole deliverable, which for a report is
hundreds of round-trips, not the nine of a paginated page.

``SsotFindingRepository`` resolves the whole page in a fixed number of queries:
one accounting aggregate, one findings read, one board read for exactly those
finding ids, one assignee prefetch. The count is compared against itself at two
row counts — never asserted as a brittle absolute.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from components.report.application.ports.finding_source_port import FindingQuery
from components.report.infrastructure.repositories.ssot_finding_repository import (
    SsotFindingRepository,
)
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    from infrastructure.persistence.project.models import Column

    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])
    column = Column.objects.create(team=team, workspace=ws, project=None, title="Todo", order=0, created_by=owner)
    return ws, owner, team, column


def _finding_with_card(ws, owner, team, column, assignees):
    from infrastructure.persistence.project.models import Task

    now = timezone.now()
    finding = Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint=f"fp-{uuid.uuid4()}",
        asset_urn=f"arn:aws:s3:::b-{uuid.uuid4()}",
        severity="medium",
        status="open",
        title="Public bucket",
        first_seen_at=now,
        last_seen_at=now,
    )
    task = Task.objects.create(
        team=team,
        workspace=ws,
        column=column,
        created_by=owner,
        title=finding.title,
        source_type="ai.cloud_posture",
        metadata={"severity": "medium", "payload": {"finding_id": str(finding.id)}},
    )
    task.assigned_to.set(assignees)
    return finding


def _read_query_count(ws) -> int:
    with CaptureQueriesContext(connection) as ctx:
        page = SsotFindingRepository().list_findings(FindingQuery(workspace_id=str(ws.id)))
        # Force the mapping build — a lazy queryset would hide the N+1.
        assert all(f["triage"]["on_board"] for f in page.findings)
    return len(ctx.captured_queries)


def test_report_finding_read_query_count_is_constant(workspace_factory, team_factory, user_factory):
    ws, owner, team, column = _board(workspace_factory, team_factory)
    people = [user_factory() for _ in range(3)]

    for _ in range(2):
        _finding_with_card(ws, owner, team, column, people[:1])
    baseline = _read_query_count(ws)

    # 10x the findings AND 3x the assignees per card must not grow the count.
    for _ in range(20):
        _finding_with_card(ws, owner, team, column, people)
    assert _read_query_count(ws) == baseline, (
        "the report's finding read must not scale with the number of findings or assignees"
    )
    # Sanity: the guard is meaningful only if it is a small constant.
    assert baseline <= 6, f"expected a handful of queries for the whole page, got {baseline}"
