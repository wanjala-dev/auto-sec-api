"""Port: the cross-context reads the sign-off task materializer needs.

The materializer projects the pending-sign-off queue onto the agents "AI
Findings" Kanban. To do that it must read three facts that live in OTHER
contexts' persistence:

* the ``Workspace`` row (``workspace`` context) — passed straight into the
  agents facades (``ensure_agents_board`` / ``persist_finding_as_task``), which
  need the live ORM object;
* the set of workspace ids that have an active AI-agents ``Team`` (``team``
  context) — the sweep's iteration set;
* the sign-off ``Task`` rows already on the board (``project`` context) — the
  reconcile pass reads their column/status + artifact ref to decide the
  terminal move.

Rather than importing ``infrastructure.persistence.{workspaces,team,project}``
from the sign-off *application* layer (Rule 2 / architecture-skill C2–C3: a
context never reads another context's ORM directly), the materializer asks
through this port. The ORM adapter that implements it lives in
``components/sign_off/infrastructure/adapters/`` — the sanctioned inbound-read
pattern mirroring ``remediation``'s ``BoardFindingFactsRepository`` and
``project``'s own ``OrmTaskLookupRepository``.

Every method is workspace-scoped where a workspace is in play (tenant
isolation): a task/row from another workspace is never returned.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SignOffTaskRef:
    """A materialized sign-off task as the reconcile pass reads it.

    Carries only the columns the reconcile needs — the task id, its current
    board column + status (to decide whether a terminal move is required and
    keep it idempotent), and the artifact ref pulled from
    ``metadata.context`` (to look up the artifact's final review state). Never
    an ORM row.
    """

    task_id: str
    column_id: str | None
    status: str
    artifact_type: str | None
    artifact_id: str | None


class SignOffBoardPort(ABC):
    """Secondary read port for the sign-off task materializer."""

    @abstractmethod
    def get_workspace(self, workspace_id: str) -> Any | None:
        """Return the ``Workspace`` ORM object for *workspace_id*, or ``None``.

        The live object is required because it is handed straight to the agents
        facades (``ensure_agents_board`` / ``persist_finding_as_task``).
        """

    @abstractmethod
    def list_agents_workspace_ids(self) -> list[str]:
        """Return every workspace id that has an ACTIVE AI-agents team.

        This is the sweep's iteration set — the workspaces whose pending
        sign-off queue can be projected onto an agents board. De-duplicated,
        ``None`` ids dropped.
        """

    @abstractmethod
    def list_signoff_tasks(self, *, workspace_id: str, source_type: str) -> list[SignOffTaskRef]:
        """Return every materialized sign-off task in *workspace_id*.

        Filters on ``(workspace_id, source_type)`` — the tuple the materializer
        stamps on each card — and shapes each row into a :class:`SignOffTaskRef`.
        Workspace-scoped: a row from another workspace is never returned.
        """
