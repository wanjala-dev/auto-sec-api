"""Use case: materialise a workspace's ranked attack paths (ADR 0004 §6 / ADR 0005 §6).

The heavy correlation: read the (node-capped) asset graph, run the AttackPathAnalyzer
domain service, replace the workspace's materialised paths, and emit ``AttackPathDetected``
for each. Called from the background detector cycle (never inline in a request). The HUD
reads the materialised rows through a thin CQRS query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.cloud_graph.application.ports.attack_path_store_port import AttackPathStorePort
from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort
from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity
from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.shared_kernel.domain.events import AttackPathDetected

_MAX_NODES = 500


@dataclass(frozen=True)
class MaterializeAttackPathsResult:
    paths_found: int
    assets_scanned: int
    edges_scanned: int


def _to_event(path: AttackPathEntity) -> AttackPathDetected:
    return AttackPathDetected(
        workspace_id=path.workspace_id,
        path_id=path.id,
        severity=path.severity.value,
        title=path.title,
        asset_urns=list(path.asset_urns),
        finding_ids=[],  # populated once paths link back to contributing findings (ADR 0005 phase 3)
    )


class MaterializeAttackPathsUseCase:
    def __init__(
        self,
        asset_store: CloudAssetStorePort,
        path_store: AttackPathStorePort,
        analyzer: AttackPathAnalyzer,
        publisher=None,
    ):
        self._assets = asset_store
        self._paths = path_store
        self._analyzer = analyzer
        self._publisher = publisher

    def execute(self, workspace_id: UUID, now: datetime) -> MaterializeAttackPathsResult:
        assets = self._assets.list_assets(workspace_id, limit=_MAX_NODES)
        edges = self._assets.list_all_edges(workspace_id)
        paths = self._analyzer.analyze(assets, edges, workspace_id=workspace_id, now=now)
        # replace_for_workspace commits before we publish, so no on-commit dance is needed:
        # the rows are durable by the time an AttackPathDetected subscriber can run.
        self._paths.replace_for_workspace(workspace_id, paths)
        if self._publisher is not None:
            for path in paths:
                self._publisher.publish(_to_event(path))
        return MaterializeAttackPathsResult(
            paths_found=len(paths), assets_scanned=len(assets), edges_scanned=len(edges)
        )
