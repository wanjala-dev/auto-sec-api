"""Integration tests for the cross-context sample-data coordinator (ADR 0011 Phases 2+3).

Covers the coordinator seeding findings + cloud graph together, complete teardown across
both contexts (no orphans), the mutual-exclusivity guards (skip a workspace with real
data), and that the graph read paths include the sample rows (that's the demo).
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from components.sample_data.application.providers.sample_data_provider import SampleDataProvider


def _finding_count(ws_id, *, sample_only=True):
    from infrastructure.persistence.findings.models import Finding

    qs = Finding.objects.filter(workspace_id=ws_id)
    if sample_only:
        qs = qs.filter(source__startswith="sample.")
    return qs.count()


def _asset_count(ws_id, *, sample_only=True):
    from infrastructure.persistence.cloud_graph.models import CloudAsset

    qs = CloudAsset.objects.filter(workspace_id=ws_id)
    if sample_only:
        qs = qs.filter(is_sample=True)
    return qs.count()


def _edge_count(ws_id, *, sample_only=True):
    from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

    qs = CloudAssetEdge.objects.filter(workspace_id=ws_id)
    if sample_only:
        qs = qs.filter(is_sample=True)
    return qs.count()


def _path_count(ws_id, *, sample_only=True):
    from infrastructure.persistence.cloud_graph.models import AttackPath

    qs = AttackPath.objects.filter(workspace_id=ws_id)
    if sample_only:
        qs = qs.filter(is_sample=True)
    return qs.count()


@pytest.mark.django_db
class TestSampleDataCoordinator:
    def test_seed_populates_findings_and_graph_together(self, workspace_factory):
        ws = workspace_factory()
        result = SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())

        seeded = result["seeded"]
        assert seeded["findings"]["seeded"] > 0
        assert seeded["cloud_graph"]["seeded_assets"] > 0
        assert seeded["cloud_graph"]["seeded_edges"] > 0
        assert seeded["cloud_graph"]["seeded_paths"] > 0

        assert _finding_count(ws.id) > 0
        assert _asset_count(ws.id) > 0
        assert _edge_count(ws.id) > 0
        assert _path_count(ws.id) > 0

    def test_clear_removes_all_sample_rows_across_contexts(self, workspace_factory):
        ws = workspace_factory()
        facade = SampleDataProvider.build_facade()
        facade.seed(ws.id, now=timezone.now())
        assert _asset_count(ws.id) > 0 and _finding_count(ws.id) > 0

        facade.clear(ws.id)

        # No orphans in EITHER context.
        assert _finding_count(ws.id) == 0
        assert _asset_count(ws.id) == 0
        assert _edge_count(ws.id) == 0
        assert _path_count(ws.id) == 0

    def test_sample_asset_urns_match_sample_findings(self, workspace_factory):
        """Coherence: seeded graph assets share asset_urns with the sample findings, so the
        graph and findings correlate into one story."""
        from infrastructure.persistence.cloud_graph.models import CloudAsset
        from infrastructure.persistence.findings.models import Finding

        ws = workspace_factory()
        SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())

        asset_urns = set(CloudAsset.objects.filter(workspace_id=ws.id).values_list("asset_urn", flat=True))
        finding_urns = set(
            Finding.objects.filter(workspace_id=ws.id, source__startswith="sample.").values_list("asset_urn", flat=True)
        )
        # At least the toxic-path anchors must overlap (S3 bucket, SG, IAM user, RDS).
        assert "urn:aws:s3:::acme-analytics-exports" in asset_urns & finding_urns
        assert "urn:aws:rds:us-east-1:db:acme-prod" in asset_urns & finding_urns
        assert "urn:aws:iam::123456789012:user/ci-deployer" in asset_urns & finding_urns

    def test_graph_read_includes_sample_assets_and_paths(self, workspace_factory):
        """The HUD reads must SHOW the sample rows — they are the demo."""
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.application.queries.get_asset_graph_query import GetAssetGraphQuery
        from components.cloud_graph.application.queries.list_attack_paths_query import ListAttackPathsQuery

        ws = workspace_factory()
        SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())

        view = CloudGraphProvider.build_get_asset_graph_use_case().execute(GetAssetGraphQuery(workspace_id=ws.id))
        assert view.total_nodes > 0
        assert len(view.edges) > 0

        paths = CloudGraphProvider.build_list_attack_paths_use_case().execute(ListAttackPathsQuery(workspace_id=ws.id))
        assert len(paths) > 0
        # The crown-jewel toxic path is present.
        assert any(p.target_asset_urn == "urn:aws:rds:us-east-1:db:acme-prod" for p in paths)

    def test_exposure_summary_reflects_public_sample_assets(self, workspace_factory):
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider

        ws = workspace_factory()
        SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())

        store = CloudGraphProvider.build_cloud_asset_store()
        by_exposure = store.count_by_exposure(ws.id)
        assert by_exposure.get("public", 0) > 0


@pytest.mark.django_db
class TestSampleDataGuards:
    def test_findings_seed_skips_workspace_with_real_findings(self, workspace_factory):
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.domain.entities.finding_entity import FindingEntity
        from components.shared_kernel.domain.security import FindingStatus, Severity

        ws = workspace_factory()
        # A real (non-sample) finding present.
        FindingProvider.build_finding_store().upsert(
            FindingEntity(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                source="cloud_posture.prowler",
                fingerprint="real-1",
                asset_urn="urn:aws:s3:::real-bucket",
                severity=Severity.HIGH,
                status=FindingStatus.OPEN,
                title="real finding",
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            )
        )
        result = SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())
        assert result["seeded"]["findings"]["skipped"] is True
        assert _finding_count(ws.id) == 0  # no sample findings injected

    def test_graph_seed_skips_workspace_with_real_assets(self, workspace_factory):
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
        from components.cloud_graph.domain.value_objects.enums import Exposure

        ws = workspace_factory()
        # A real (non-sample) asset present.
        CloudGraphProvider.build_cloud_asset_store().upsert_asset(
            CloudAssetEntity(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                provider="aws",
                arn="arn:aws:s3:::real-prod-bucket",
                asset_urn="urn:aws:s3:::real-prod-bucket",
                resource_type="aws_s3_bucket",
                exposure=Exposure.PRIVATE,
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            )
        )
        result = SampleDataProvider.build_facade().seed(ws.id, now=timezone.now())
        assert result["seeded"]["cloud_graph"]["skipped"] is True
        assert _asset_count(ws.id, sample_only=True) == 0

    def test_clear_leaves_real_rows_untouched(self, workspace_factory):
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
        from components.cloud_graph.domain.value_objects.enums import Exposure

        ws = workspace_factory()
        store = CloudGraphProvider.build_cloud_asset_store()
        store.upsert_asset(
            CloudAssetEntity(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                provider="aws",
                arn="arn:aws:s3:::real-prod-bucket",
                asset_urn="urn:aws:s3:::real-prod-bucket",
                resource_type="aws_s3_bucket",
                exposure=Exposure.PRIVATE,
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            )
        )
        # Clear on a workspace whose only assets are real: removes nothing real.
        SampleDataProvider.build_facade().clear(ws.id)
        assert _asset_count(ws.id, sample_only=False) == 1
