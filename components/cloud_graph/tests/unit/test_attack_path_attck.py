"""ATT&CK mapping for attack-path categories + its emission onto the finding."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from components.cloud_graph.application.use_cases.materialize_attack_paths_use_case import (
    _to_finding_observed,
)
from components.cloud_graph.domain.services.attack_path_attck import techniques_for_category
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.shared_kernel.domain.mitre import TECHNIQUES, MitreTactic

pytestmark = pytest.mark.unit


class TestCategoryMapping:
    def test_public_compute_admin_flow(self):
        ids = [t.technique_id for t in techniques_for_category(AttackPathCategory.PUBLIC_COMPUTE_ADMIN)]
        assert ids == ["T1190", "T1078.004", "T1098.003"]  # Initial Access → Priv-Esc

    def test_public_data_exposure_flow(self):
        ids = [t.technique_id for t in techniques_for_category(AttackPathCategory.PUBLIC_DATA_EXPOSURE)]
        assert ids == ["T1190", "T1530"]  # Initial Access → Collection

    def test_every_category_starts_at_initial_access(self):
        for category in AttackPathCategory:
            flow = techniques_for_category(category)
            assert flow[0].tactic is MitreTactic.INITIAL_ACCESS

    def test_every_mapped_id_is_in_the_catalogue(self):
        # No mapping may reference a technique that isn't curated in shared_kernel.
        for category in AttackPathCategory:
            for t in techniques_for_category(category):
                assert t.technique_id in TECHNIQUES


def _fake_path(category=AttackPathCategory.PUBLIC_COMPUTE_ADMIN):
    return SimpleNamespace(
        workspace_id=uuid.uuid4(),
        id=uuid.uuid4(),
        severity=SimpleNamespace(value="high"),
        title="Public EC2 can assume admin role",
        explanation="i-abc is internet-facing and can assume AdminRole.",
        entry_asset_urn="arn:aws:ec2:us-east-1:123456789012:instance/i-abc",
        target_asset_urn="arn:aws:iam::123456789012:role/AdminRole",
        entry_label="i-abc",
        target_label="AdminRole",
        category=category,
        risk_score=91,
        length=2,
        asset_urns=["arn:aws:ec2:us-east-1:123456789012:instance/i-abc"],
        legs=[SimpleNamespace(src_label="i-abc", relation="can_assume", dst_label="AdminRole")],
    )


class TestFindingEmission:
    def test_compliance_carries_attack_ids(self):
        finding = _to_finding_observed(_fake_path())
        assert finding.compliance == {"MITRE ATT&CK": ["T1190", "T1078.004", "T1098.003"]}

    def test_attributes_carry_rendered_flow_in_order(self):
        finding = _to_finding_observed(_fake_path(AttackPathCategory.PUBLIC_DATA_EXPOSURE))
        mitre = finding.attributes["mitre"]
        assert [m["technique_id"] for m in mitre] == ["T1190", "T1530"]
        assert mitre[0]["tactic"] == "initial_access"
        assert mitre[0]["name"] == "Exploit Public-Facing Application"
        assert mitre[0]["url"].startswith("https://attack.mitre.org/")
