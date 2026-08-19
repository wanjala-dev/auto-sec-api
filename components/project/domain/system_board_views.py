"""The canonical system ``BoardView`` shapes (ADR 0030 §2).

A board is a saved view. Two of them are DERIVED — never authored by a
person, never editable (``SystemBoardViewImmutableError``):

* the **team board** — the unfiltered view over the team's status lanes;
* one **project board** per project — a ``{"project": "<id>"}`` view.

Migration ``project.0008`` minted exactly these for every team and project
that existed when the P1 backfill ran. This module is the ONE description of
their shape, so the runtime seam
(``components/project/infrastructure/adapters/django_system_board_view_bridge.py``)
and the ``project.0011`` repair migration cannot drift from each other or
from that backfill — the same reason the status half of 0008 shares
``workflow_status_vocabulary`` with its runtime bridge.

Pure domain: frozen dataclasses and strings, no Django, no ORM — which is
also what lets a migration import it safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The team board: every card on the team, no filter. Order 0 keeps it first
#: in the views bar (the model orders by ``("order", "id")``).
TEAM_BOARD_VIEW_SLUG = "board"
TEAM_BOARD_VIEW_NAME = "Board"
TEAM_BOARD_VIEW_ORDER = 0

#: Project views are ``project-<pk>`` — stable across renames, unique per
#: team by construction (``uniq_board_view_slug_per_team``).
PROJECT_BOARD_VIEW_SLUG_PREFIX = "project-"

#: Every system view groups by status; ADR 0030 has no other axis yet.
SYSTEM_BOARD_VIEW_GROUP_BY = "status"

#: ``BoardView.name`` is a CharField(255); a project title is the same width,
#: but slice defensively so a wider title can never make a row unsaveable.
_MAX_NAME_LENGTH = 255


@dataclass(frozen=True)
class SystemBoardViewSpec:
    """The identity + content of one system view, ready to persist."""

    slug: str
    name: str
    filter: dict[str, str]
    group_by: str = SYSTEM_BOARD_VIEW_GROUP_BY


def project_board_view_slug(project_id: Any) -> str:
    """The stable slug for a project board's system view."""
    return f"{PROJECT_BOARD_VIEW_SLUG_PREFIX}{project_id}"


def team_board_view_spec() -> SystemBoardViewSpec:
    """The unfiltered team board."""
    return SystemBoardViewSpec(slug=TEAM_BOARD_VIEW_SLUG, name=TEAM_BOARD_VIEW_NAME, filter={})


def project_board_view_spec(*, project_id: Any, title: Any) -> SystemBoardViewSpec:
    """One project board, filtered to that project.

    The filter value is ``str(project_id)`` — the exact shape the 0008
    backfill wrote and ``apply_view_filter`` reads.
    """
    name = (str(title) if title is not None else "").strip() or f"Project {project_id}"
    return SystemBoardViewSpec(
        slug=project_board_view_slug(project_id),
        name=name[:_MAX_NAME_LENGTH],
        filter={"project": str(project_id)},
    )
