"""Shared input validation for the saved-view write use cases (task #74).

Framework-free — raises the workspace domain's ``WorkspaceValidationError``
(→ 400 at the controller). Shape checks only: the closed filter VOCABULARY
is deliberately NOT re-validated here — that check lives once, on the model
(``BoardView._validate_filter``, ADR 0030), and reaches the API through the
repository translating the model's rejection (dry-reuse.md: one enforcement
point per invariant).
"""

from __future__ import annotations

from typing import Any

from components.workspace.domain.errors import WorkspaceValidationError

#: The only lane grouping that exists today (lanes ARE the team's workflow
#: statuses — ADR 0030). Accepting other values would store a promise nothing
#: renders; extend deliberately when a second grouping ships.
SUPPORTED_GROUP_BYS = ("status",)

MAX_VIEW_NAME_LENGTH = 255


def validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceValidationError("View name is required.")
    cleaned = name.strip()
    if len(cleaned) > MAX_VIEW_NAME_LENGTH:
        raise WorkspaceValidationError(f"View name must be at most {MAX_VIEW_NAME_LENGTH} characters.")
    return cleaned


def validate_filter_shape(view_filter: Any) -> dict:
    if not isinstance(view_filter, dict):
        raise WorkspaceValidationError("filter must be a JSON object of closed-vocabulary keys.")
    return view_filter


def validate_group_by(group_by: Any) -> str:
    if group_by not in SUPPORTED_GROUP_BYS:
        raise WorkspaceValidationError(
            f"Unsupported group_by {group_by!r}. Supported: {', '.join(SUPPORTED_GROUP_BYS)}."
        )
    return group_by


def validate_order(order: Any) -> int:
    # bool is an int subclass — reject it explicitly (True as an order is a bug).
    if isinstance(order, bool) or not isinstance(order, int):
        try:
            order = int(str(order))
        except (TypeError, ValueError):
            raise WorkspaceValidationError("order must be an integer.") from None
    return order
