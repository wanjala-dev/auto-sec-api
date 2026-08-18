"""Port: board-view write operations — persisted saved views (task #74).

No Django imports. The mutation seam is deliberately narrower than the read
seam it sits beside (``board_view_query_port``): only NON-SYSTEM rows are
ever writable — system views (the P1 backfill + P3 Intake/Acting seeds) are
the team's shared boards and stay immutable through this port by contract,
not by caller discipline.
"""

from __future__ import annotations

import abc
from typing import Any

from components.workspace.application.commands.board_view_commands import (
    CreateBoardViewCommand,
    UpdateBoardViewCommand,
)


class BoardViewMutationPort(abc.ABC):
    """Secondary port for saved-view writes (flag ``feature.boards_as_views``).

    Visibility/authorization contract (shared with the read seam):

    * A personal (non-system) view belongs to its creator. Anyone else in the
      workspace gets the same 404 as a missing id — EXCEPT workspace
      admins/owners, who may manage (and therefore see) any personal view in
      their workspace, mirroring the admin bypass on every other board
      operation (``check_team_membership``).
    * Cross-workspace ids always answer 404, never 403 (tenancy invariant 8).
    * ``created_by`` comes from the authenticated user — NEVER from input
      (mass-assignment protection, tenancy invariant 4); ``is_system`` is
      always False for rows written here.
    """

    @abc.abstractmethod
    def create_view(self, *, command: CreateBoardViewCommand, user: Any) -> Any:
        """Persist a new personal view for ``user`` on the team.

        The row is appended after the team's existing views
        (``order = max(order) + 1``) with a slug derived from the name and
        de-duplicated against ``uniq_board_view_slug_per_team``.

        Raises:
            WorkspaceNotFoundError: unknown team OR requester outside the
                team's workspace.
            TeamMembershipRequiredError: workspace member who is not a team
                member (admins/owners bypass).
            WorkspaceValidationError: filter outside the closed vocabulary
                (validated through the model's own check — one enforcement
                point, ADR 0030).
        """
        ...

    @abc.abstractmethod
    def update_view(self, *, command: UpdateBoardViewCommand, user: Any) -> Any:
        """Apply a partial update (rename / re-filter / reorder) and return the row.

        Raises:
            WorkspaceNotFoundError: unknown view, cross-workspace requester,
                or another user's personal view (invisible → same 404).
            SystemBoardViewImmutableError: the view is a system view (403 —
                the row's existence is not a secret; its immutability is the
                message).
            WorkspaceValidationError: filter outside the closed vocabulary.
        """
        ...

    @abc.abstractmethod
    def delete_view(self, *, view_id: Any, user: Any) -> None:
        """Delete a personal view. Same visibility/immutability contract as
        :meth:`update_view`."""
        ...
