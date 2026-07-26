"""AttackPathAnalyzer — the CNAPP toxic-combination correlation (the owned risk logic).

Given a workspace's asset graph (nodes + typed edges), find the ranked attack paths:
a PUBLIC workload that reaches a crown-jewel SINK (admin privileges or sensitive data)
through entitlement/reach edges. This is a framework-free Domain Service (architecture
skill §4 "attack-path is a Domain Service"); the §6 background job feeds it the graph
and persists what it returns. A bounded BFS over the Postgres-stored graph (ADR 0004 D8
— no graph DB), not a recursive CTE: the traversal is small (node-capped) and the
toxic-combination scoring — our differentiator — stays here, pure and unit-testable,
rather than encoded in SQL.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime

from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity, AttackPathLeg
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.cloud_graph.domain.value_objects.enums import Exposure
from components.shared_kernel.domain.security import Severity

# Stable namespace so a path's id is idempotent across re-materialisations
# (same entry→target→category ⇒ same id ⇒ no churn on the HUD / event stream).
_PATH_NS = uuid.UUID("a7c3e1d2-0000-4000-8000-000000000001")

MAX_DEPTH = 6  # bound the walk; real toxic combinations are short (2–4 hops)

_WORKLOAD_HINTS = ("instance", "ec2", "lambda", "function", "container", "ecs", "compute", "vm")
_ADMIN_HINTS = ("admin", "administrator", "poweruser")
_DATA_HINTS = ("bucket", "s3", "rds", "database", "dynamo", "redshift")

_BASE_SCORE = {
    AttackPathCategory.PUBLIC_COMPUTE_ADMIN: 80.0,
    AttackPathCategory.PUBLIC_DATA_EXPOSURE: 65.0,
}


def _label(asset: CloudAssetEntity) -> str:
    return asset.name or asset.arn.rsplit("/", 1)[-1] or asset.resource_type


def _is_workload(resource_type: str) -> bool:
    rt = resource_type.lower()
    return any(h in rt for h in _WORKLOAD_HINTS)


def _sink_category(asset: CloudAssetEntity) -> AttackPathCategory | None:
    """A crown-jewel sink: an admin policy/role, or a sensitive data store. Else None."""
    rt = asset.resource_type.lower()
    text = f"{asset.name} {asset.arn}".lower()
    if "policy" in rt and (any(h in text for h in _ADMIN_HINTS) or "*" in text):
        return AttackPathCategory.PUBLIC_COMPUTE_ADMIN
    if any(h in rt for h in _DATA_HINTS):
        return AttackPathCategory.PUBLIC_DATA_EXPOSURE
    return None


class AttackPathAnalyzer:
    def analyze(
        self,
        assets: list[CloudAssetEntity],
        edges: list[CloudAssetEdgeEntity],
        *,
        workspace_id: uuid.UUID,
        now: datetime,
    ) -> list[AttackPathEntity]:
        by_id = {a.id: a for a in assets}
        adjacency: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
        for e in edges:
            if e.src_asset_id in by_id and e.dst_asset_id in by_id:
                adjacency.setdefault(e.src_asset_id, []).append((e.dst_asset_id, e.relation.value))

        entries = [a for a in assets if a.exposure is Exposure.PUBLIC and _is_workload(a.resource_type)]
        paths: list[AttackPathEntity] = []
        for entry in entries:
            paths.extend(self._paths_from(entry, adjacency, by_id, workspace_id, now))

        # Rank: highest contextual risk first; ties broken by the shorter (more direct) path.
        paths.sort(key=lambda p: (p.risk_score, -p.length), reverse=True)
        return paths

    def _paths_from(self, entry, adjacency, by_id, workspace_id, now) -> list[AttackPathEntity]:
        found: list[AttackPathEntity] = []
        seen_targets: set[uuid.UUID] = set()
        # BFS ⇒ the first path found to any sink is the shortest.
        queue: deque[tuple[uuid.UUID, list[AttackPathLeg]]] = deque([(entry.id, [])])
        visited = {entry.id}
        while queue:
            node_id, legs = queue.popleft()
            if len(legs) >= MAX_DEPTH:
                continue
            for dst_id, relation in adjacency.get(node_id, []):
                dst = by_id[dst_id]
                leg = AttackPathLeg(
                    src_id=node_id,
                    src_label=_label(by_id[node_id]),
                    relation=relation,
                    dst_id=dst_id,
                    dst_label=_label(dst),
                )
                next_legs = [*legs, leg]
                category = _sink_category(dst)
                if category is not None:
                    if dst_id not in seen_targets:
                        seen_targets.add(dst_id)
                        found.append(self._build(entry, dst, next_legs, category, by_id, workspace_id, now))
                    continue  # a sink terminates the path; don't traverse beyond it
                if dst_id not in visited:
                    visited.add(dst_id)
                    queue.append((dst_id, next_legs))
        return found

    def _build(self, entry, target, legs, category, by_id, workspace_id, now) -> AttackPathEntity:
        score = self._score(category, legs, target)
        entry_label, target_label = _label(entry), _label(target)
        chain = [entry_label, *[leg.dst_label for leg in legs]]
        relations = " → ".join(f"-[{leg.relation}]→ {leg.dst_label}" for leg in legs)
        return AttackPathEntity(
            id=uuid.uuid5(_PATH_NS, f"{workspace_id}:{entry.id}:{target.id}:{category.value}"),
            workspace_id=workspace_id,
            category=category,
            severity=self._severity(score),
            risk_score=score,
            entry_asset_id=entry.id,
            entry_asset_urn=entry.asset_urn,
            entry_label=entry_label,
            target_asset_id=target.id,
            target_asset_urn=target.asset_urn,
            target_label=target_label,
            title=f"Public {entry.resource_type} '{entry_label}' can reach {target_label}",
            explanation=f"{entry_label} (public {entry.resource_type}) {relations}",
            legs=tuple(legs),
            asset_urns=tuple([entry.asset_urn, *[by_id[leg.dst_id].asset_urn for leg in legs]]),
            computed_at=now,
        )

    @staticmethod
    def _score(category: AttackPathCategory, legs, target: CloudAssetEntity) -> float:
        score = _BASE_SCORE[category]
        if len(legs) <= 2:
            score += 8.0  # direct reach is worse than a long chain
        text = f"{target.name} {target.arn}".lower()
        if category is AttackPathCategory.PUBLIC_COMPUTE_ADMIN and ("administrator" in text or "*" in text):
            score += 7.0  # full-admin sink, not just elevated
        return max(0.0, min(100.0, score))

    @staticmethod
    def _severity(score: float) -> Severity:
        if score >= 85:
            return Severity.CRITICAL
        if score >= 65:
            return Severity.HIGH
        if score >= 40:
            return Severity.MEDIUM
        if score >= 20:
            return Severity.LOW
        return Severity.INFORMATIONAL
