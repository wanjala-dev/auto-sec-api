"""Unit tests for the cloud exposure / asset-inventory summary (pure + use case)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.cloud_graph.application.use_cases.get_exposure_summary_use_case import (
    GetExposureSummaryUseCase,
)
from components.cloud_graph.domain.services.exposure_summary import build

pytestmark = pytest.mark.unit


class _FakeAssetStore:
    def __init__(self, by_exposure, by_type, public_urns):
        self._by_exposure = by_exposure
        self._by_type = by_type
        self._public_urns = public_urns

    def count_by_exposure(self, workspace_id):
        return self._by_exposure

    def count_by_type(self, workspace_id, *, top=8):
        return self._by_type[:top]

    def list_public_asset_urns(self, workspace_id):
        return self._public_urns


class _FakeFindingStore:
    def __init__(self, at_risk_urns):
        self._at_risk = at_risk_urns
        self.calls = []

    def open_finding_asset_urns(self, workspace_id, *, severities):
        self.calls.append(severities)
        return set(self._at_risk)


class _FakePath:
    def __init__(self, score):
        self.risk_score = score


class _FakePathStore:
    def __init__(self, n):
        self._paths = [_FakePath(50.0) for _ in range(n)]

    def list_for_workspace(self, workspace_id, *, category=None, min_score=None, limit=50):
        return self._paths


def test_build_intersects_public_with_at_risk_by_urn():
    summary = build(
        by_exposure={"public": 7, "internal": 21, "private": 172},
        by_type=[("AwsIamPolicy", 15), ("AwsS3Bucket", 4)],
        public_asset_urns={"urn:a", "urn:b", "urn:c"},
        at_risk_asset_urns={"urn:b", "urn:c", "urn:z"},  # urn:z is not public
        attack_path_count=4,
    )
    assert summary.total_assets == 200
    assert summary.public == 7
    assert summary.internal == 21
    assert summary.private == 172
    # only the public URNs that ALSO carry an open crit/high finding
    assert summary.public_at_risk == 2  # b, c (not z — not public; not a — no finding)
    assert summary.attack_paths == 4


def test_to_dict_shape():
    summary = build(
        by_exposure={"public": 2, "private": 8},
        by_type=[("AwsEc2Instance", 3)],
        public_asset_urns={"urn:a"},
        at_risk_asset_urns={"urn:a"},
        attack_path_count=1,
    )
    d = summary.to_dict()
    assert d["total_assets"] == 10
    assert d["exposure"] == {"public": 2, "internal": 0, "private": 8}
    assert d["by_type"] == [{"type": "AwsEc2Instance", "count": 3}]
    assert d["attack_surface"] == {"public_assets": 2, "public_at_risk": 1, "attack_paths": 1}


def test_use_case_gathers_and_correlates():
    ws = uuid4()
    findings = _FakeFindingStore(at_risk_urns={"urn:pub1", "urn:other"})
    use_case = GetExposureSummaryUseCase(
        asset_store=_FakeAssetStore(
            by_exposure={"public": 3, "internal": 5, "private": 40},
            by_type=[("AwsIamRole", 11), ("AwsS3Bucket", 4)],
            public_urns=["urn:pub1", "urn:pub2", "urn:pub3"],
        ),
        finding_store=findings,
        attack_path_store=_FakePathStore(2),
    )
    summary = use_case.execute(ws)

    assert summary.total_assets == 48
    assert summary.public == 3
    assert summary.public_at_risk == 1  # only urn:pub1 is both public and at-risk
    assert summary.attack_paths == 2
    # correlation asks for crit + high open findings
    assert findings.calls == [("critical", "high")]
