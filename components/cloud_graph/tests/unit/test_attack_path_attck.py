"""ATT&CK mapping for attack-path categories + its emission onto the finding."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from components.cloud_graph.application.use_cases.materialize_attack_paths_use_case import (
    _to_finding_observed,
)
from components.cloud_graph.domain.services.attack_path_attck import (
    build_attack_flow,
    technique_for_relation,
    techniques_for_category,
)
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.shared_kernel.domain.mitre import TECHNIQUES, MitreTactic

pytestmark = pytest.mark.unit


def _leg(relation, dst_label="dst"):
    return SimpleNamespace(src_label="src", relation=relation, dst_label=dst_label)


class TestRelationMapping:
    def test_known_relations_map_to_techniques(self):
        assert technique_for_relation("can_assume").technique_id == "T1078.004"
        assert technique_for_relation("has_policy").technique_id == "T1098.003"
        assert technique_for_relation("reads_bucket").technique_id == "T1530"
        assert technique_for_relation("allows_ingress_from").technique_id == "T1190"

    def test_structural_relation_has_no_technique(self):
        assert technique_for_relation("attached_to") is None
        assert technique_for_relation("in_subnet") is None

    def test_every_relation_technique_is_catalogued(self):
        for rel in ("can_assume", "has_policy", "reads_bucket", "allows_ingress_from", "routes_to_igw"):
            assert technique_for_relation(rel).technique_id in TECHNIQUES


class TestAttackFlow:
    def test_flow_starts_at_public_entry(self):
        flow = build_attack_flow("i-abc", [_leg("can_assume", "AdminRole")])
        assert flow[0]["label"] == "i-abc"
        assert flow[0]["technique_id"] == "T1190"  # entry = Initial Access
        assert flow[0]["relation"] is None

    def test_flow_appends_one_step_per_mapped_leg(self):
        flow = build_attack_flow(
            "i-abc",
            [_leg("can_assume", "role"), _leg("has_policy", "AdminPolicy"), _leg("reads_bucket", "secrets")],
        )
        assert [s["technique_id"] for s in flow] == ["T1190", "T1078.004", "T1098.003", "T1530"]
        assert flow[1]["label"] == "role" and flow[1]["relation"] == "can_assume"

    def test_structural_legs_are_skipped(self):
        flow = build_attack_flow("i-abc", [_leg("attached_to"), _leg("can_assume", "role")])
        assert [s["technique_id"] for s in flow] == ["T1190", "T1078.004"]


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

    def test_attributes_carry_per_hop_attack_flow(self):
        # slice 2: entry (Initial Access) then the can_assume leg (Priv-Esc).
        finding = _to_finding_observed(_fake_path())
        flow = finding.attributes["attack_flow"]
        assert [s["technique_id"] for s in flow] == ["T1190", "T1078.004"]
        assert flow[0]["label"] == "i-abc" and flow[0]["relation"] is None
        assert flow[1]["label"] == "AdminRole" and flow[1]["relation"] == "can_assume"

    def test_remediation_is_specific_not_generic(self):
        # The ticket's remediation names the entry + crown-jewel target (the grounded
        # advisor), not the old one-size-fits-all "strip the over-privileged policy" line.
        finding = _to_finding_observed(_fake_path())
        assert "i-abc" in finding.remediation and "AdminRole" in finding.remediation
        assert finding.remediation != (
            "Break the chain: remove the public exposure of the entry asset, or strip the "
            "over-privileged role/policy it can reach."
        )
