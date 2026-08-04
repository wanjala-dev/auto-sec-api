"""N+1 regression guard for the findings list with tag chips (perf rule §1, ADR 0015 D7).

``GET /findings/workspaces/<ws>/`` serves the ranked read; each row now carries its
live tag refs. The repository prefetches the join in ONE extra query
(``Prefetch("tag_links", …, to_attr="prefetched_tag_links")``), so the total query
count must be constant w.r.t. BOTH the number of findings on the page AND the
number of tags per finding. Counts are compared, never asserted as absolutes.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding, FindingTag
from infrastructure.persistence.tagging.models import Tag
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _finding(ws):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint=f"fp-{uuid.uuid4()}",
        asset_urn=f"arn:aws:s3:::{uuid.uuid4()}",
        severity="high",
        status="open",
        title="Public bucket",
        first_seen_at=now,
        last_seen_at=now,
    )


def _tag_finding(ws, finding, tags):
    FindingTag.objects.bulk_create(
        [FindingTag(workspace=ws, finding=finding, tag=tag) for tag in tags],
        ignore_conflicts=True,
    )


def _list_query_count(api_client, ws) -> int:
    with CaptureQueriesContext(connection) as ctx:
        res = api_client.get(f"/api/v1/findings/workspaces/{ws.id}/")
        assert res.status_code == 200, res.content
    return len(ctx.captured_queries)


def test_findings_list_query_count_is_constant(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    api_client.force_authenticate(member)

    tags = [Tag.objects.create(workspace=ws, name=f"t{i}", slug=f"t{i}") for i in range(3)]
    for _ in range(2):
        _tag_finding(ws, _finding(ws), tags[:2])

    # Warm one-time caches so the baseline reflects steady state.
    _list_query_count(api_client, ws)
    baseline = _list_query_count(api_client, ws)

    # More findings AND more tags per finding must not grow the count — an N+1
    # would add one tag_links query per row (or per chip).
    for _ in range(4):
        _tag_finding(ws, _finding(ws), tags)
    grown = _list_query_count(api_client, ws)

    assert grown == baseline, (
        f"Findings-list N+1 regression: {baseline} queries with 2 findings×2 tags "
        f"but {grown} with 6 findings×(2-3) tags — the count must be constant "
        "w.r.t. rows and chips."
    )


def test_tag_filtered_list_query_count_is_constant(api_client, workspace_factory, user_factory):
    """The tag filter (Exists subqueries) must not add per-row queries either."""
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    api_client.force_authenticate(member)

    tag = Tag.objects.create(workspace=ws, name="hot", slug="hot")
    other = Tag.objects.create(workspace=ws, name="cold", slug="cold")
    for _ in range(2):
        _tag_finding(ws, _finding(ws), [tag])

    def count():
        with CaptureQueriesContext(connection) as ctx:
            res = api_client.get(f"/api/v1/findings/workspaces/{ws.id}/?tag=hot&exclude_tag=cold")
            assert res.status_code == 200, res.content
        return len(ctx.captured_queries), len(res.data["data"]["items"])

    count()
    baseline, n_before = count()
    for _ in range(4):
        _tag_finding(ws, _finding(ws), [tag, other][:1])
    grown, n_after = count()

    assert n_after > n_before  # the filter actually matched the new rows
    assert grown == baseline, (
        f"Tag-filtered list N+1 regression: {baseline} queries for {n_before} rows but {grown} for {n_after}."
    )
