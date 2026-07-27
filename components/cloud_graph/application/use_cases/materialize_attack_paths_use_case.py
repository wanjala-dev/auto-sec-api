"""Use case: materialise a workspace's ranked attack paths (ADR 0004 §6 / ADR 0005 §6).

The heavy correlation: read the (node-capped) asset graph, run the AttackPathAnalyzer
domain service, replace the workspace's materialised paths, and emit — per path — both
``AttackPathDetected`` (the graph-correlation signal) and ``FindingObserved`` (so the path
becomes a first-class finding in the SSOT, boards, and gets triaged; ADR 0005 phase 3).
Called from the background detector cycle (never inline in a request). The HUD reads the
materialised rows through a thin CQRS query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.cloud_graph.application.ports.attack_path_store_port import AttackPathStorePort
from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort
from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity
from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.cloud_graph.domain.services.attack_path_attck import build_attack_flow, techniques_for_category
from components.shared_kernel.domain.events import AttackPathDetected, FindingObserved

# Source tag for the Finding SSOT (owner-persists on FindingObserved) + the board handler
# lookup (`finding_raised_board_handler._SOURCE_BOARD`). Born SSOT-native (graduated) — no
# legacy board dual-write / cutover, unlike logwatch.
FINDING_SOURCE = "cloud_graph.attack_path"
_TRIAGE_SPECIALIST = "triage_agent"  # the generic SOC triager the router dispatches to

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


def _to_finding_observed(path: AttackPathEntity) -> FindingObserved:
    """Map a ranked path → a FindingObserved for the SSOT (owner-persists, C2).

    ``asset_urn`` is the ENTRY (the exposed foothold) so this finding correlates by value
    (C4) with any posture finding on the same asset — the triage agent sees both. The
    ``attributes`` carry everything the board-card builder + router need: the routing
    target (``triage_agent``), the impact score, and the path legs as evidence.

    ATT&CK: the path category maps deterministically to a kill-chain-ordered technique
    set. The technique ids ride in ``compliance`` (ATT&CK is a framework mapping, like
    CIS — no new contract), and a rendered copy (id + name + tactic) rides in
    ``attributes["mitre"]`` so the board/HUD show the attack-flow without a lookup.
    """
    techniques = techniques_for_category(path.category)
    return FindingObserved(
        workspace_id=path.workspace_id,
        source=FINDING_SOURCE,
        fingerprint=f"attack_path:{path.id}",
        asset_urn=path.entry_asset_urn,
        severity=path.severity.value,
        title=path.title,
        description=path.explanation,
        remediation=(
            "Break the chain: remove the public exposure of the entry asset, or strip the "
            "over-privileged role/policy it can reach."
        ),
        compliance={"MITRE ATT&CK": [t.technique_id for t in techniques]},
        attributes={
            "agent_type": _TRIAGE_SPECIALIST,
            "impact_score": int(path.risk_score),
            "category": path.category.value,
            "category_label": path.category.label,
            "risk_score": path.risk_score,
            "length": path.length,
            "entry_label": path.entry_label,
            "entry_asset_urn": path.entry_asset_urn,
            "target_label": path.target_label,
            "target_asset_urn": path.target_asset_urn,
            "asset_urns": list(path.asset_urns),
            "mitre": [t.to_dict() for t in techniques],
            "attack_flow": build_attack_flow(path.entry_label, path.legs),
            "legs": [
                {"src_label": leg.src_label, "relation": leg.relation, "dst_label": leg.dst_label} for leg in path.legs
            ],
        },
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
                self._publisher.publish(_to_finding_observed(path))
        return MaterializeAttackPathsResult(
            paths_found=len(paths), assets_scanned=len(assets), edges_scanned=len(edges)
        )
