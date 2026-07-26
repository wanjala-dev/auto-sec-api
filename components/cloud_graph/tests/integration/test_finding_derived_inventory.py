"""Integration: the Prowler/SSOT-derived inventory sync builds cloud assets.

Seeds cloud-posture findings in the Finding SSOT (as the prowler dual-write does) and
asserts the sync materializes CloudAssets — idempotently, workspace-scoped, with
distinct-resource aggregation and heuristic exposure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.cloud_graph.domain.value_objects.enums import Exposure
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _seed_finding(
    ws,
    *,
    fingerprint,
    resource_uid,
    resource_type="aws_s3_bucket",
    check_id="s3_bucket_public_access",
    region="us-east-1",
    account="123456789012",
):
    DjangoFindingRepository().upsert(
        FindingEntity(
            id=uuid4(),
            workspace_id=ws.id,
            source="cloud_posture.prowler",
            fingerprint=fingerprint,
            asset_urn=resource_uid,
            severity=Severity.HIGH,
            status=FindingStatus.OPEN,
            title=check_id,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            attributes={
                "check_id": check_id,
                "resource_uid": resource_uid,
                "resource_type": resource_type,
                "region": region,
                "account_id": account,
                "resource_name": "res",
            },
        )
    )


def _sync(ws):
    return CloudGraphProvider.build_sync_cloud_assets_use_case().execute(ws.id)


class TestFindingDerivedInventory:
    def test_materializes_assets_with_type_and_exposure(self, workspace_factory):
        ws = workspace_factory()
        _seed_finding(
            ws,
            fingerprint="fp-s3",
            resource_uid="arn:aws:s3:::bucket-a",
            resource_type="aws_s3_bucket",
            check_id="s3_bucket_public_access",
        )
        _seed_finding(
            ws,
            fingerprint="fp-ec2",
            resource_uid="arn:aws:ec2:us-east-1:1:instance/i-1",
            resource_type="aws_ec2_instance",
            check_id="ec2_ebs_default_encryption",
        )

        result = _sync(ws)
        assert result.assets_upserted == 2
        assert result.findings_scanned == 2

        store = CloudGraphProvider.build_cloud_asset_store()
        bucket = store.get_asset_by_arn(ws.id, "arn:aws:s3:::bucket-a")
        assert bucket is not None
        assert bucket.resource_type == "aws_s3_bucket"
        assert bucket.exposure is Exposure.PUBLIC  # public-access check → PUBLIC
        assert bucket.attributes.get("account_id") == "123456789012"

        ec2 = store.get_asset_by_arn(ws.id, "arn:aws:ec2:us-east-1:1:instance/i-1")
        assert ec2.exposure is Exposure.PRIVATE  # encryption check → not public

    def test_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        _seed_finding(ws, fingerprint="fp1", resource_uid="arn:aws:s3:::b")
        _sync(ws)
        _sync(ws)
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        assert CloudAsset.objects.filter(workspace=ws).count() == 1

    def test_distinct_resource_aggregation_public_wins(self, workspace_factory):
        # Two findings on the SAME resource, one public one not → ONE asset, PUBLIC.
        ws = workspace_factory()
        _seed_finding(ws, fingerprint="fp-a", resource_uid="arn:aws:s3:::same", check_id="s3_bucket_versioning")
        _seed_finding(ws, fingerprint="fp-b", resource_uid="arn:aws:s3:::same", check_id="s3_bucket_public_access")

        result = _sync(ws)
        assert result.assets_upserted == 1
        store = CloudGraphProvider.build_cloud_asset_store()
        assert store.get_asset_by_arn(ws.id, "arn:aws:s3:::same").exposure is Exposure.PUBLIC

    def test_workspace_scoped(self, workspace_factory):
        ws = workspace_factory()
        other = workspace_factory()
        _seed_finding(ws, fingerprint="fp-mine", resource_uid="arn:aws:s3:::mine")
        _seed_finding(other, fingerprint="fp-theirs", resource_uid="arn:aws:s3:::theirs")

        _sync(ws)
        store = CloudGraphProvider.build_cloud_asset_store()
        assert store.get_asset_by_arn(ws.id, "arn:aws:s3:::mine") is not None
        assert store.get_asset_by_arn(ws.id, "arn:aws:s3:::theirs") is None
