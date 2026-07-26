"""Django adapter implementing AttackPathStorePort — materialised read table."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction

from components.cloud_graph.application.ports.attack_path_store_port import AttackPathStorePort
from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity
from components.cloud_graph.mappers.db.attack_path_mapper import (
    to_attack_path_entity,
    to_attack_path_model_kwargs,
)


class DjangoAttackPathRepository(AttackPathStorePort):
    def replace_for_workspace(self, workspace_id: UUID, paths: list[AttackPathEntity]) -> int:
        from infrastructure.persistence.cloud_graph.models import AttackPath

        with transaction.atomic():
            AttackPath.objects.filter(workspace_id=workspace_id).delete()
            if not paths:
                return 0
            AttackPath.objects.bulk_create(AttackPath(**to_attack_path_model_kwargs(p)) for p in paths)
        return len(paths)

    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        category: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
    ) -> list[AttackPathEntity]:
        from infrastructure.persistence.cloud_graph.models import AttackPath

        qs = AttackPath.objects.filter(workspace_id=workspace_id)
        if category:
            qs = qs.filter(category=category)
        if min_score is not None:
            qs = qs.filter(risk_score__gte=min_score)
        rows = qs.order_by("-risk_score", "length")[:limit]
        return [to_attack_path_entity(obj) for obj in rows]
