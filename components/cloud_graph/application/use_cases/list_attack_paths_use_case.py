"""Use case: read a workspace's ranked attack paths (thin CQRS read over the table)."""

from __future__ import annotations

from components.cloud_graph.application.ports.attack_path_store_port import AttackPathStorePort
from components.cloud_graph.application.queries.list_attack_paths_query import ListAttackPathsQuery
from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity


class ListAttackPathsUseCase:
    def __init__(self, path_store: AttackPathStorePort):
        self._paths = path_store

    def execute(self, query: ListAttackPathsQuery) -> list[AttackPathEntity]:
        return self._paths.list_for_workspace(
            query.workspace_id,
            category=query.category,
            min_score=query.min_score,
            limit=query.limit,
        )
