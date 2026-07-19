"""Shared workspace write-access helpers.

Centralises the permission check used when deciding whether a user
may mutate a workspace-scoped entity (campaign, event, recipient,
project, etc.). Historically each repository duplicated a bespoke
``Campaign.objects.filter(user_id=user_id)`` style check, which
broke as soon as a workspace member other than the original creator
tried to edit shared content. See the 2026-04-11 campaign goal bug
where a non-creator workspace member hit a 404 on PATCH.

Usage (in a repository)
-----------------------
::

    from components.shared_platform.infrastructure.services.workspace_access import (
        workspace_writer_q,
    )

    def get_campaign_for_user(self, campaign_id, user_id):
        return (
            Campaign.objects
            .filter(id=campaign_id)
            .filter(workspace_writer_q(user_id))
            .distinct()
            .first()
        )

The returned ``Q`` assumes the target model has either a ``user``
FK (legacy creator) or a ``workspace`` FK (or both). If only one
applies, it still evaluates correctly — the other clause simply
never matches.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q


def workspace_writer_q(
    user_id: Any,
    *,
    workspace_field: str = "workspace",
    creator_field: str | None = "user_id",
) -> Q:
    """Return a ``Q`` that matches rows a user may **mutate**.

    A user can mutate a workspace-scoped row when they are:

    * The original creator (legacy ``user`` FK), for back-compat.
    * The workspace owner (``Workspace.workspace_owner``).
    * An active workspace member with a **write** role — owner,
      admin or member. Viewers are read-only and excluded.

    Parameters
    ----------
    user_id:
        ``request.user.id`` (string or int).
    workspace_field:
        Name of the FK on the target model that points to
        ``Workspace``. Defaults to ``"workspace"``.
    creator_field:
        Name of the legacy creator FK on the target model, or
        ``None`` if the model has no creator concept. Defaults to
        ``"user_id"``.
    """

    # Local import to avoid circular imports — this module is
    # intentionally lightweight and must not pull Django models at
    # import time so it can be imported from anywhere.
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    write_roles = [
        WorkspaceMembership.Role.OWNER,
        WorkspaceMembership.Role.ADMIN,
        WorkspaceMembership.Role.MEMBER,
    ]

    q = Q(**{f"{workspace_field}__workspace_owner_id": user_id}) | Q(
        **{
            f"{workspace_field}__memberships__user_id": user_id,
            f"{workspace_field}__memberships__status": (
                WorkspaceMembership.Status.ACTIVE
            ),
            f"{workspace_field}__memberships__role__in": write_roles,
        }
    )

    if creator_field:
        q = Q(**{creator_field: user_id}) | q

    return q
