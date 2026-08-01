"""ORM ↔ domain mapper for materialised attack paths."""

from __future__ import annotations

from uuid import UUID

from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity, AttackPathLeg
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.shared_kernel.domain.security import Severity


def _leg_to_dict(leg: AttackPathLeg) -> dict:
    return {
        "src_id": str(leg.src_id),
        "src_label": leg.src_label,
        "relation": leg.relation,
        "dst_id": str(leg.dst_id),
        "dst_label": leg.dst_label,
    }


def _leg_from_dict(d: dict) -> AttackPathLeg:
    return AttackPathLeg(
        src_id=UUID(d["src_id"]),
        src_label=d.get("src_label", ""),
        relation=d.get("relation", ""),
        dst_id=UUID(d["dst_id"]),
        dst_label=d.get("dst_label", ""),
    )


def to_attack_path_model_kwargs(entity: AttackPathEntity) -> dict:
    """Full kwargs for ``AttackPath.objects.create`` / bulk_create (id included)."""
    return {
        "id": entity.id,
        "workspace_id": entity.workspace_id,
        "category": entity.category.value,
        "severity": entity.severity.value,
        "risk_band": entity.risk_band.value,
        "risk_score": entity.risk_score,
        "entry_asset_id": entity.entry_asset_id,
        "entry_asset_urn": entity.entry_asset_urn,
        "entry_label": entity.entry_label,
        "target_asset_id": entity.target_asset_id,
        "target_asset_urn": entity.target_asset_urn,
        "target_label": entity.target_label,
        "title": entity.title,
        "explanation": entity.explanation,
        "length": entity.length,
        "legs": [_leg_to_dict(leg) for leg in entity.legs],
        "asset_urns": list(entity.asset_urns),
        "computed_at": entity.computed_at,
        "is_sample": entity.is_sample,
    }


def to_attack_path_entity(obj) -> AttackPathEntity:
    return AttackPathEntity(
        id=obj.id,
        workspace_id=obj.workspace_id,
        category=AttackPathCategory(obj.category),
        severity=Severity(obj.severity),
        risk_score=obj.risk_score,
        entry_asset_id=obj.entry_asset_id,
        entry_asset_urn=obj.entry_asset_urn,
        entry_label=obj.entry_label,
        target_asset_id=obj.target_asset_id,
        target_asset_urn=obj.target_asset_urn,
        target_label=obj.target_label,
        title=obj.title,
        explanation=obj.explanation,
        legs=tuple(_leg_from_dict(d) for d in (obj.legs or [])),
        asset_urns=tuple(obj.asset_urns or []),
        computed_at=obj.computed_at,
        is_sample=obj.is_sample,
    )
