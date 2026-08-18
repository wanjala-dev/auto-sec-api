"""Port: board-view read operations — boards as views over team statuses (ADR 0030 P2a).

No Django imports — depends only on the standard library. The windowing
contract (default window, hard ceiling, clamping) is SHARED with the column
board via ``column_query_port`` so the two board reads cannot drift apart
while both exist (P2 dual-read; P4 retires the column read).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from components.workspace.application.ports.column_query_port import ColumnTasksPage


@dataclass(frozen=True)
class ViewBoard:
    """One view's board: the ``BoardView`` row plus its team's status lanes.

    ``statuses`` follow the column board's lane contract exactly: each row
    carries ``windowed_tasks`` (the first ``tasks_limit`` matching live tasks
    in board order, eager-loaded for everything ``TaskSerializer`` reads) and
    ``tasks_total`` (matching live-task count for the lane badge / load-more
    affordance).
    """

    view: Any
    statuses: list[Any]


class BoardViewQueryPort(abc.ABC):
    """Secondary port for the boards-as-views reads (flag ``feature.boards_as_views``)."""

    @abc.abstractmethod
    def fetch_team_views(self, *, team_id: Any, user: Any) -> list[Any]:
        """Return the team's ``BoardView`` rows in views-bar order.

        System views first, then the requester's OWN personal views (task
        #74) appended after — another user's personal views are never
        returned, to anyone (personal views are per-user, not team-shared).

        Raises:
            WorkspaceNotFoundError: unknown team, OR the requester is not a
                member of the team's workspace. Cross-tenant probes get the
                same 404 as a missing id — existence is never leaked across
                the workspace boundary (tenancy invariant 8).
            TeamMembershipRequiredError: workspace member who is not a team
                member (workspace admins/owners bypass, mirroring the column
                board read).
        """
        ...

    @abc.abstractmethod
    def fetch_view_board(self, *, view_id: Any, user: Any, tasks_limit: int) -> ViewBoard:
        """Return one view's board: ordered status lanes + windowed matching tasks.

        Lanes are the team's ``WorkflowStatus`` rows (ordered, with category);
        lane membership is ``task.workflow_status`` restricted by the view's
        closed-vocabulary ``filter``. Same windowing/eager-loading/ordering
        contract as :meth:`ColumnQueryPort.fetch_columns`.

        Raises:
            WorkspaceNotFoundError: unknown view, requester outside the
                view's workspace, OR another user's personal view (invisible
                → the same non-leaking 404; workspace admins/owners bypass).
            TeamMembershipRequiredError: workspace member, not a team member.
        """
        ...

    @abc.abstractmethod
    def fetch_view_lane_tasks(
        self, *, view_id: Any, status_id: Any, user: Any, offset: int, limit: int
    ) -> ColumnTasksPage:
        """Return one window of a single status lane's matching tasks.

        The view board's "load more" read — the exact analog of
        :meth:`ColumnQueryPort.fetch_column_tasks`, with the view's filter
        applied so paging continues the same lane the board rendered. Same
        ordering + eager-loading contract as the windows attached by
        :meth:`fetch_view_board`; consecutive windows never skip or duplicate
        cards.

        Raises:
            WorkspaceNotFoundError: unknown view/status, cross-workspace
                requester, or a status that does not belong to the view's team.
            TeamMembershipRequiredError: workspace member, not a team member.
        """
        ...
