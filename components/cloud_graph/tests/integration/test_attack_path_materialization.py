"""Integration: the attack-path materialisation job (analyze → replace table → emit)."""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from components.cloud_graph.application.use_cases.materialize_attack_paths_use_case import (
    MaterializeAttackPathsUseCase,
)
from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.cloud_graph.infrastructure.repositories.django_attack_path_repository import (
    DjangoAttackPathRepository,
)
from components.cloud_graph.infrastructure.repositories.django_cloud_graph_repository import (
    DjangoCloudGraphRepository,
)
from infrastructure.persistence.cloud_graph.models import AttackPath, CloudAsset, CloudAssetEdge

pytestmark = [pytest.mark.django_db]


class _FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def _asset(ws, arn, rtype, exposure, name):
    now = timezone.now()
    return CloudAsset.objects.create(
        id=uuid.uuid4(),
        workspace=ws,
        arn=arn,
        asset_urn=f"urn:{rtype}:{arn}",
        resource_type=rtype,
        region="us-east-1",
        name=name,
        exposure=exposure,
        first_seen_at=now,
        last_seen_at=now,
    )


def _edge(ws, src, dst, relation):
    CloudAssetEdge.objects.create(
        id=uuid.uuid4(), workspace=ws, src_asset=src, dst_asset=dst, relation=relation, last_seen_at=timezone.now()
    )


def _toxic_graph(ws):
    ec2 = _asset(ws, "arn:ec2:web", "aws_ec2_instance", "public", "web-frontend")
    role = _asset(ws, "arn:iam:role", "aws_iam_role", "private", "app-exec-role")
    admin = _asset(ws, "arn:iam:admin", "aws_iam_policy", "private", "AdministratorAccess")
    data = _asset(ws, "arn:s3:data", "aws_s3_bucket", "internal", "customer-data")
    _edge(ws, ec2, role, "can_assume")
    _edge(ws, role, admin, "has_policy")
    _edge(ws, role, data, "reads_bucket")


def _use_case(publisher):
    return MaterializeAttackPathsUseCase(
        asset_store=DjangoCloudGraphRepository(),
        path_store=DjangoAttackPathRepository(),
        analyzer=AttackPathAnalyzer(),
        publisher=publisher,
    )


class TestAttackPathMaterialization:
    def test_materializes_ranked_paths_and_emits_events(self, workspace_factory):
        ws = workspace_factory()
        _toxic_graph(ws)
        pub = _FakePublisher()

        result = _use_case(pub).execute(ws.id, timezone.now())

        assert result.paths_found == 2
        rows = list(AttackPath.objects.filter(workspace=ws).order_by("-risk_score"))
        assert len(rows) == 2
        assert rows[0].category == "public_compute_admin"
        assert rows[0].severity == "critical"
        assert rows[0].risk_band == "red"
        assert rows[0].length == 2
        assert rows[0].risk_score > rows[1].risk_score
        # one AttackPathDetected + one FindingObserved per path (ADR 0005 phase 3)
        from components.shared_kernel.domain.events import AttackPathDetected, FindingObserved

        detected = [e for e in pub.events if isinstance(e, AttackPathDetected)]
        observed = [e for e in pub.events if isinstance(e, FindingObserved)]
        assert len(detected) == 2
        assert {e.path_id for e in detected} == {r.id for r in rows}
        assert len(observed) == 2
        assert {e.source for e in observed} == {"cloud_graph.attack_path"}
        assert {e.fingerprint for e in observed} == {f"attack_path:{r.id}" for r in rows}

    def test_finding_observed_carries_triage_routing_and_evidence(self, workspace_factory):
        from components.shared_kernel.domain.events import FindingObserved

        ws = workspace_factory()
        _toxic_graph(ws)
        pub = _FakePublisher()
        _use_case(pub).execute(ws.id, timezone.now())

        observed = [e for e in pub.events if isinstance(e, FindingObserved)]
        admin = next(e for e in observed if e.severity == "critical")
        # asset_urn is the ENTRY foothold (correlates with posture findings on it, C4)
        assert admin.asset_urn == "urn:aws_ec2_instance:arn:ec2:web"
        assert admin.attributes["agent_type"] == "triage_agent"  # the triage router target
        assert admin.attributes["category"] == "public_compute_admin"
        assert admin.attributes["impact_score"] == 95
        assert [leg["relation"] for leg in admin.attributes["legs"]] == ["can_assume", "has_policy"]

    def test_is_idempotent_replace_not_duplicate(self, workspace_factory):
        ws = workspace_factory()
        _toxic_graph(ws)
        _use_case(_FakePublisher()).execute(ws.id, timezone.now())
        ids_first = set(AttackPath.objects.filter(workspace=ws).values_list("id", flat=True))

        _use_case(_FakePublisher()).execute(ws.id, timezone.now())
        rows = AttackPath.objects.filter(workspace=ws)
        assert rows.count() == 2  # replaced, not doubled
        assert set(rows.values_list("id", flat=True)) == ids_first  # stable ids

    def test_no_paths_when_no_public_entry(self, workspace_factory):
        ws = workspace_factory()
        role = _asset(ws, "arn:iam:role", "aws_iam_role", "private", "role")
        admin = _asset(ws, "arn:iam:admin", "aws_iam_policy", "private", "AdministratorAccess")
        _edge(ws, role, admin, "has_policy")

        result = _use_case(_FakePublisher()).execute(ws.id, timezone.now())
        assert result.paths_found == 0
        assert AttackPath.objects.filter(workspace=ws).count() == 0

    def test_scoped_to_workspace(self, workspace_factory):
        ws = workspace_factory()
        other = workspace_factory()
        _toxic_graph(ws)
        _toxic_graph(other)

        _use_case(_FakePublisher()).execute(ws.id, timezone.now())
        assert AttackPath.objects.filter(workspace=ws).count() == 2
        assert AttackPath.objects.filter(workspace=other).count() == 0  # only ws materialised
