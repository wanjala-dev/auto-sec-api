"""Adapter: the cross-context reads the sign-off task materializer needs.

Implements :class:`SignOffBoardPort`. This is the sanctioned inbound-read
pattern: the sign-off context defines a port shaped to its need, and this
infrastructure adapter reads the shared persistence models
(``infrastructure.persistence.{workspaces,team,project}``). Reading a
persistence model is NOT a ``components.<other>.infrastructure`` import — it
does not cross the component-infrastructure boundary the architecture tests
guard (same rationale as ``remediation``'s ``BoardFindingFactsRepository`` and
``project``'s ``OrmTaskLookupRepository``).

Reads are workspace-scoped where a workspace is in play (tenant isolation) and
use ``.only(...)`` / ``.values_list(...)`` to pull just the columns the caller
consumes.
"""

from __future__ import annotations

from typing import Any

from components.sign_off.application.ports.sign_off_board_port import (
    SignOffBoardPort,
    SignOffTaskRef,
)


class OrmSignOffBoardRepository(SignOffBoardPort):
    def get_workspace(self, workspace_id: str) -> Any | None:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).first()

    def list_agents_workspace_ids(self) -> list[str]:
        from infrastructure.persistence.team.models import Team

        workspace_ids = (
            Team.objects.filter(kind=Team.Kind.AI_AGENTS, status=Team.ACTIVE)
            .values_list("workspace_id", flat=True)
            .distinct()
        )
        return [str(wid) for wid in workspace_ids.iterator(chunk_size=500) if wid is not None]

    def list_signoff_tasks(self, *, workspace_id: str, source_type: str) -> list[SignOffTaskRef]:
        from infrastructure.persistence.project.models import Task

        rows = (
            Task.objects.filter(workspace_id=workspace_id, source_type=source_type)
            .only("id", "column_id", "status", "metadata")
            .iterator(chunk_size=500)
        )
        refs: list[SignOffTaskRef] = []
        for task in rows:
            context = (task.metadata or {}).get("context") or {}
            refs.append(
                SignOffTaskRef(
                    task_id=str(task.id),
                    column_id=str(task.column_id) if task.column_id else None,
                    status=task.status,
                    artifact_type=context.get("artifact_type"),
                    artifact_id=context.get("artifact_id"),
                )
            )
        return refs
