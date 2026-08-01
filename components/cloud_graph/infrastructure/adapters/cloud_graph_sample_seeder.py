"""CloudGraphSampleSeeder — the cloud_graph SampleDataSeederPort adapter (ADR 0011 Phase 3).

Seeds a COHERENT sample cloud environment (assets + typed edges + materialised attack
paths) so the asset graph / map / attack-surface / risk-gauge populate under demo mode.
The fixture's ``asset_urn``s match the sample findings, so the graph and findings tell one
story. Everything is written DIRECTLY through the store's sample seams (tagged
``is_sample=True``) — the attack paths are seeded, NOT run through the real
``materialize_attack_paths`` detector — so no events, scans, or side-effects fire.

Guard: skip if the workspace already holds REAL cloud assets (mutual exclusivity, mirrors
``has_real_findings``). Teardown removes only ``is_sample=True`` rows.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from uuid import UUID

from components.cloud_graph.application.ports.attack_path_store_port import AttackPathStorePort
from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort
from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity, AttackPathLeg
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.services.attack_path_analyzer import _PATH_NS
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure
from components.cloud_graph.infrastructure.sample_cloud_graph import (
    SAMPLE_ASSETS,
    SAMPLE_ATTACK_PATHS,
    SAMPLE_EDGES,
    relation_for,
)
from components.sample_data.application.ports.sample_data_seeder_port import SampleDataSeederPort
from components.shared_kernel.domain.security import Severity

logger = logging.getLogger(__name__)


class CloudGraphSampleSeeder(SampleDataSeederPort):
    def __init__(self, *, asset_store: CloudAssetStorePort, path_store: AttackPathStorePort) -> None:
        self._assets = asset_store
        self._paths = path_store

    @property
    def context(self) -> str:
        return "cloud_graph"

    def has_real_data(self, workspace_id: UUID) -> bool:
        return self._assets.has_real_assets(UUID(str(workspace_id)))

    def seed(self, workspace_id: UUID, *, now: datetime) -> dict:
        ws = UUID(str(workspace_id))
        if self._assets.has_real_assets(ws):
            logger.info("cloud_graph sample seed skipped — workspace has real assets ws=%s", ws)
            return {"seeded_assets": 0, "seeded_edges": 0, "seeded_paths": 0, "skipped": True}

        # Build the assets in-memory (stable uuid4 ids) — keep a key → entity map so edges
        # and attack paths can reference asset ids without a DB round-trip.
        by_key: dict[str, CloudAssetEntity] = {
            row["key"]: CloudAssetEntity(
                id=uuid.uuid4(),
                workspace_id=ws,
                provider="aws",
                arn=row["arn"],
                asset_urn=row["asset_urn"],
                resource_type=row["resource_type"],
                exposure=Exposure.from_value(row["exposure"]),
                region=row["region"],
                name=row["name"],
                attributes=dict(row["attributes"]),
                first_seen_at=now,
                last_seen_at=now,
                is_sample=True,
            )
            for row in SAMPLE_ASSETS
        }
        edge_entities = [
            CloudAssetEdgeEntity(
                id=uuid.uuid4(),
                workspace_id=ws,
                src_asset_id=by_key[src_key].id,
                dst_asset_id=by_key[dst_key].id,
                relation=AssetRelation.from_value(relation),
                last_seen_at=now,
                is_sample=True,
            )
            for src_key, relation, dst_key in SAMPLE_EDGES
        ]

        # One atomic, clear-sample-first write — idempotent on re-seed (no UNIQUE clash).
        seeded_assets, seeded_edges = self._assets.seed_sample_graph(ws, list(by_key.values()), edge_entities)
        paths = [self._build_path(ws, spec, by_key, now) for spec in SAMPLE_ATTACK_PATHS]
        seeded_paths = self._paths.seed_sample_paths(ws, paths)

        logger.info(
            "cloud_graph sample seeded ws=%s assets=%s edges=%s paths=%s",
            ws,
            seeded_assets,
            seeded_edges,
            seeded_paths,
        )
        return {
            "seeded_assets": seeded_assets,
            "seeded_edges": seeded_edges,
            "seeded_paths": seeded_paths,
            "skipped": False,
        }

    def clear(self, workspace_id: UUID) -> dict:
        ws = UUID(str(workspace_id))
        deleted_paths = self._paths.clear_sample_paths(ws)
        deleted_assets = self._assets.clear_sample_assets(ws)  # cascades sample edges
        logger.info("cloud_graph sample cleared ws=%s assets=%s paths=%s", ws, deleted_assets, deleted_paths)
        return {"deleted_assets": deleted_assets, "deleted_paths": deleted_paths}

    def _build_path(self, ws: UUID, spec: dict, by_key: dict, now: datetime) -> AttackPathEntity:
        entry = by_key[spec["entry_key"]]
        target = by_key[spec["target_key"]]
        category = AttackPathCategory(spec["category"])
        leg_chain = [by_key[k] for k in spec["leg_keys"]]
        legs = tuple(
            AttackPathLeg(
                src_id=leg_chain[i].id,
                src_label=leg_chain[i].name,
                relation=relation_for(spec["leg_keys"][i], spec["leg_keys"][i + 1]),
                dst_id=leg_chain[i + 1].id,
                dst_label=leg_chain[i + 1].name,
            )
            for i in range(len(leg_chain) - 1)
        )
        return AttackPathEntity(
            id=uuid.uuid5(_PATH_NS, f"{ws}:{entry.id}:{target.id}:{category.value}"),
            workspace_id=ws,
            category=category,
            severity=Severity(spec["severity"]),
            risk_score=float(spec["risk_score"]),
            entry_asset_id=entry.id,
            entry_asset_urn=entry.asset_urn,
            entry_label=entry.name,
            target_asset_id=target.id,
            target_asset_urn=target.asset_urn,
            target_label=target.name,
            title=spec["title"],
            explanation=spec["explanation"],
            legs=legs,
            asset_urns=tuple(a.asset_urn for a in leg_chain),
            computed_at=now,
            is_sample=True,
        )
