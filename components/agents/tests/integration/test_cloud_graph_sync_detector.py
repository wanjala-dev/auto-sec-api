"""The cloud_graph.sync detector: flag-gated cadence + graph materialization.

Slice 2 detector — should_run gates on feature.cloud_asset_graph (+ a lease), and
execute drives the cloud_graph sync use case (materialize assets, emit no findings yet).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest import mock
from uuid import uuid4

import pytest

from components.agents.domain.detectors.base import DetectorContext
from components.agents.infrastructure.adapters.actions.detectors.cloud_graph_sync import (
    CloudGraphSyncDetector,
)
from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


@contextmanager
def _flag(enabled: bool):
    stub = mock.Mock()
    stub.is_feature_enabled.return_value = enabled
    with mock.patch(
        "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider",
        return_value=stub,
    ):
        yield


def _ctx(ws):
    return DetectorContext(workspace_id=str(ws.id), teammate_id="t-1", run_at=_NOW, last_run_at=None)


def _seed_finding(ws, *, resource_uid, check_id="s3_bucket_public_access"):
    DjangoFindingRepository().upsert(
        FindingEntity(
            id=uuid4(),
            workspace_id=ws.id,
            source="cloud_posture.prowler",
            fingerprint=f"fp-{resource_uid}",
            asset_urn=resource_uid,
            severity=Severity.HIGH,
            status=FindingStatus.OPEN,
            title=check_id,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            attributes={"check_id": check_id, "resource_uid": resource_uid, "resource_type": "aws_s3_bucket"},
        )
    )


class TestCloudGraphSyncDetector:
    def test_should_run_is_gated_on_the_flag_and_lease(self, workspace_factory):
        from django.core.cache import cache

        ws = workspace_factory()
        det = CloudGraphSyncDetector()

        with _flag(False):
            assert det.should_run(_ctx(ws)) is False

        cache.delete(f"cloud_graph_sync:lease:{ws.id}")
        with _flag(True):
            assert det.should_run(_ctx(ws)) is True  # acquires the lease
            assert det.should_run(_ctx(ws)) is False  # lease held → self-gated

    def test_execute_materializes_assets_and_emits_no_findings(self, workspace_factory):
        ws = workspace_factory()
        _seed_finding(ws, resource_uid="arn:aws:s3:::bucket-x")

        results = list(CloudGraphSyncDetector().execute(_ctx(ws)))

        assert results == []  # slice 2 materializes only; exposure findings come later
        asset = CloudGraphProvider.build_cloud_asset_store().get_asset_by_arn(ws.id, "arn:aws:s3:::bucket-x")
        assert asset is not None
        assert asset.resource_type == "aws_s3_bucket"

    def test_registered_in_the_detector_registry(self):
        from components.agents.infrastructure.adapters.actions.detectors import registry

        assert registry.get("cloud_graph.sync") is CloudGraphSyncDetector
