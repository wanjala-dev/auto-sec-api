"""Output DTO for the attack-path read API — JSON-safe ranked paths for the HUD."""

from __future__ import annotations

from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity


class AttackPathResource:
    @staticmethod
    def from_entity(p: AttackPathEntity) -> dict:
        return {
            "id": str(p.id),
            "category": p.category.value,
            "category_label": p.category.label,
            "severity": p.severity.value,
            "risk_score": round(p.risk_score, 1),
            "risk_band": p.risk_band.value,
            "length": p.length,
            "title": p.title,
            "explanation": p.explanation,
            "entry": {"id": str(p.entry_asset_id), "asset_urn": p.entry_asset_urn, "label": p.entry_label},
            "target": {"id": str(p.target_asset_id), "asset_urn": p.target_asset_urn, "label": p.target_label},
            "asset_urns": list(p.asset_urns),
            "legs": [
                {
                    "source": str(leg.src_id),
                    "source_label": leg.src_label,
                    "relation": leg.relation,
                    "target": str(leg.dst_id),
                    "target_label": leg.dst_label,
                }
                for leg in p.legs
            ],
            "computed_at": p.computed_at.isoformat() if p.computed_at else None,
        }

    @staticmethod
    def collection(paths: list[AttackPathEntity]) -> dict:
        return {"items": [AttackPathResource.from_entity(p) for p in paths], "total": len(paths)}
