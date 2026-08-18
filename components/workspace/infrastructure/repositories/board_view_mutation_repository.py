"""ORM adapter for saved-view writes (task #74, on the ADR 0030 substrate).

Implements :class:`BoardViewMutationPort`. Deliberately built ON the read
seam's resolution + membership helpers (``board_view_query_repository``) so
the write and read sides of one entity can never disagree about who may see
a view or which id 404s (dry-reuse.md).

Contract highlights:

* ``created_by`` is ALWAYS the authenticated user; ``is_system`` is ALWAYS
  False; team/workspace come from the resolved team — none of these are ever
  read from client input (mass-assignment protection, tenancy invariant 4).
* System views are immutable here — 403 with an explicit message, because
  their existence is not a secret (every team member sees them) while their
  immutability is the thing the caller needs to learn.
* Another user's personal view answers the same 404 as a missing id
  (visibility contract), except for workspace admins/owners, who may manage
  any personal view in their workspace — the same admin bypass every other
  board operation has (``check_team_membership``).
* The closed filter vocabulary is enforced by the MODEL's own check
  (``BoardView.save`` → ``_validate_filter``); this adapter only translates
  that rejection into the domain taxonomy. One enforcement point, ADR 0030.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils.text import slugify

from components.workspace.application.commands.board_view_commands import (
    CreateBoardViewCommand,
    UpdateBoardViewCommand,
)
from components.workspace.application.ports.board_view_mutation_port import BoardViewMutationPort
from components.workspace.domain.errors import (
    SystemBoardViewImmutableError,
    WorkspaceValidationError,
)
from components.workspace.infrastructure.repositories.board_view_query_repository import (
    OrmBoardViewQueryRepository,
)
from components.workspace.infrastructure.repositories.column_query_repository import (
    check_team_membership,
)

logger = logging.getLogger(__name__)

#: Slug de-dup ceiling. Personal views on one team never legitimately need
#: this many same-named rows; hitting it means something is looping.
_MAX_SLUG_ATTEMPTS = 50

#: Keep room for a de-dup suffix ("-49") inside SlugField(max_length=255).
_SLUG_BASE_MAX_LENGTH = 240

SYSTEM_VIEW_IMMUTABLE_MESSAGE = (
    "System views are immutable — they are the team's shared boards. Save a personal view instead."
)


class OrmBoardViewMutationRepository(BoardViewMutationPort):
    def create_view(self, *, command: CreateBoardViewCommand, user: Any) -> Any:
        team = OrmBoardViewQueryRepository._get_team_for_member(command.team_id, user)
        check_team_membership(user, team)

        from infrastructure.persistence.project.models import BoardView

        base_slug = slugify(command.name)[:_SLUG_BASE_MAX_LENGTH] or "view"
        taken = set(
            BoardView.objects.filter(team=team, workspace=team.workspace, slug__startswith=base_slug).values_list(
                "slug", flat=True
            )
        )

        candidates = (base_slug if n == 1 else f"{base_slug}-{n}" for n in range(1, _MAX_SLUG_ATTEMPTS + 1))
        for slug in candidates:
            if slug in taken:
                continue
            try:
                # Per-attempt savepoint: an IntegrityError from a racing
                # creator must not poison the outer transaction.
                with transaction.atomic():
                    next_order = (
                        BoardView.objects.filter(team=team, workspace=team.workspace).aggregate(max_order=Max("order"))[
                            "max_order"
                        ]
                        or 0
                    ) + 1
                    view = BoardView.objects.create(
                        workspace=team.workspace,
                        team=team,
                        name=command.name,
                        slug=slug,
                        filter=command.filter,
                        group_by=command.group_by,
                        order=next_order,
                        is_system=False,
                        created_by=user,
                    )
            except DjangoValidationError as exc:
                raise WorkspaceValidationError("; ".join(exc.messages)) from exc
            except IntegrityError:
                # Lost the uniq_board_view_slug_per_team race — next candidate.
                logger.info("board_view slug race team_id=%s slug=%s", team.id, slug)
                continue
            logger.info(
                "board_view_created view_id=%s team_id=%s workspace_id=%s user_id=%s",
                view.id,
                team.id,
                team.workspace_id,
                user.id,
            )
            return view
        raise WorkspaceValidationError("Could not allocate a unique slug for this view name.")

    def update_view(self, *, command: UpdateBoardViewCommand, user: Any) -> Any:
        view = self._get_editable_view(command.view_id, user)

        update_fields = ["updated_at"]
        if command.name is not None:
            view.name = command.name
            update_fields.append("name")
        if command.filter is not None:
            view.filter = command.filter
            update_fields.append("filter")
        if command.group_by is not None:
            view.group_by = command.group_by
            update_fields.append("group_by")
        if command.order is not None:
            view.order = command.order
            update_fields.append("order")

        try:
            # Renames keep the slug: it is the view's stable identity in the
            # bar (Linear-style); only creation mints slugs.
            view.save(update_fields=update_fields)
        except DjangoValidationError as exc:
            raise WorkspaceValidationError("; ".join(exc.messages)) from exc
        logger.info("board_view_updated view_id=%s user_id=%s fields=%s", view.id, user.id, update_fields)
        return view

    def delete_view(self, *, view_id: Any, user: Any) -> None:
        view = self._get_editable_view(view_id, user)
        view_pk = view.pk
        view.delete()
        logger.info("board_view_deleted view_id=%s user_id=%s", view_pk, user.id)

    # -- helpers --

    @staticmethod
    def _get_editable_view(view_id: Any, user: Any) -> Any:
        """Resolve a view the user may WRITE.

        Visibility (workspace 404, creator-or-admin 404 for personal views)
        is the READ seam's ``_get_view_for_member`` — one resolution for both
        sides, so read and write can never disagree about who sees a view.
        On top of it, exactly one write-only rule: system views are immutable
        (403 — their existence is known to every team member; their
        immutability is the message).
        """
        view = OrmBoardViewQueryRepository._get_view_for_member(view_id, user)
        if view.is_system:
            raise SystemBoardViewImmutableError(SYSTEM_VIEW_IMMUTABLE_MESSAGE)
        return view
