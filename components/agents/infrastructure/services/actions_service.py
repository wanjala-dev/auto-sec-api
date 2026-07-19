"""Infrastructure service coordinating AI teammate lifecycle.

Phase 5 of the Agents-as-Teammates migration deleted ``AIAction``; the
service used to also own action persistence (``log_action``,
``mark_action``, action queries, notification fan-out). All that
moved to ``components.agents.application.handlers.specialist_persistence_service``
(specialists write Tasks directly) and to ``AIFindingsViewSet`` (the
read replacement at ``/ai/findings/``).

What's left here is the teammate-lifecycle surface:

* ``ensure_teammate(workspace)`` — get-or-create the
  ``AITeammateProfile`` for a workspace, including the dedicated
  ``CustomUser`` that owns AI-authored writes (so Task.created_by is
  a real user the team-membership checks accept).
* ``get_teammate(workspace_id)`` — read-only lookup.
* ``iter_enabled_seeds()`` — the cron path enumerating workspaces with
  ``ai_teammate_enabled=True`` so ``run_ai_teammate_cycle`` knows who
  to detect for.
* ``update_last_run(teammate)`` — stamps ``last_run_at`` after a
  detector cycle finishes.

The class keeps its legacy ``AIActionService`` name for one PR to
avoid a wide rename; rename to ``AITeammateService`` in the follow-up
that cleans up the remaining naming drift.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from components.agents.infrastructure.adapters.actions.constants import (
    AI_TEAMMATE_STATUS_ACTIVE,
    DEFAULT_TEAMMATE_EMAIL_DOMAIN,
    DEFAULT_TEAMMATE_PASSWORD_LENGTH,
)
from infrastructure.persistence.ai.models import AIPermissionGrant, AITeammateProfile

try:
    from infrastructure.persistence.workspaces.models import Workspace
except ImportError:  # pragma: no cover
    Workspace = None

logger = logging.getLogger(__name__)

User = get_user_model()


class AIActionService:
    """Coordinates the AI teammate (user + profile + default grant) lifecycle.

    Despite the historical name, this no longer touches AIAction —
    Phase 5 of the Agents-as-Teammates migration moved all action
    persistence onto Task via the specialist handler pipeline.
    """

    def ensure_teammate(self, workspace: "Workspace") -> AITeammateProfile:
        if not workspace:
            raise ValueError("Workspace is required to ensure teammate")

        profile = getattr(workspace, "ai_teammate_profile", None)
        if profile:
            return profile

        db = AITeammateProfile.objects.db
        with transaction.atomic(using=db):
            return self._ensure_teammate_locked(workspace)

    def _ensure_teammate_locked(self, workspace: "Workspace") -> AITeammateProfile:
        profile = (
            AITeammateProfile.objects.select_for_update()
            .filter(workspace=workspace)
            .first()
        )
        if profile:
            return profile

        user = self._ensure_teammate_user(workspace)
        profile = AITeammateProfile.objects.create(
            workspace=workspace,
            user=user,
            status=AI_TEAMMATE_STATUS_ACTIVE,
            is_enabled=True,
            config={},
        )
        logger.info("Created Orchestrator profile for workspace %s", workspace.id)
        self._ensure_default_ai_grant(workspace=workspace, principal=user)
        return profile

    def _ensure_default_ai_grant(
        self,
        *,
        workspace: "Workspace",
        principal: User,
    ) -> AIPermissionGrant:
        grant, _ = AIPermissionGrant.objects.get_or_create(
            workspace=workspace,
            principal=principal,
            role=AIPermissionGrant.ROLE_AI_EXECUTOR,
            scope_type=AIPermissionGrant.SCOPE_WORKSPACE,
            scope_id=None,
            defaults={"status": AIPermissionGrant.STATUS_ACTIVE, "actions": ["*"]},
        )
        if grant.status != AIPermissionGrant.STATUS_ACTIVE:
            grant.status = AIPermissionGrant.STATUS_ACTIVE
            grant.save(update_fields=["status", "updated_at"])
        if grant.actions != ["*"]:
            grant.actions = ["*"]
            grant.save(update_fields=["actions", "updated_at"])
        return grant

    def _ensure_teammate_user(self, workspace: "Workspace") -> User:
        base_slug = (
            slugify(workspace.workspace_name)
            if getattr(workspace, "workspace_name", None)
            else str(workspace.id)
        )
        email = f"{base_slug}@{DEFAULT_TEAMMATE_EMAIL_DOMAIN}"
        existing = User.objects.filter(email=email).first()
        if existing:
            return existing

        suffix = 1
        unique_email = email
        while User.objects.filter(email=unique_email).exists():
            suffix += 1
            unique_email = f"{base_slug}-{suffix}@{DEFAULT_TEAMMATE_EMAIL_DOMAIN}"

        password = User.objects.make_random_password(
            length=DEFAULT_TEAMMATE_PASSWORD_LENGTH,
        )
        username = self._build_unique_username(base_slug)
        user = User.objects.create_user(
            username=username,
            email=unique_email,
            password=password,
        )
        user.first_name = workspace.workspace_name or "AI"
        user.last_name = "Teammate"
        user.is_staff = False
        user.save(update_fields=["first_name", "last_name", "is_staff"])
        logger.info(
            "Created Orchestrator user %s for workspace %s",
            user.id, workspace.id,
        )
        return user

    @staticmethod
    def _build_unique_username(base_slug: str) -> str:
        base_username = f"{base_slug}-ai"[:150]
        if not User.objects.filter(username=base_username).exists():
            return base_username

        suffix = 1
        while True:
            candidate = f"{base_username[:146]}-{suffix}"
            if not User.objects.filter(username=candidate).exists():
                return candidate
            suffix += 1

    def get_teammate(self, workspace_id: str) -> Optional[AITeammateProfile]:
        return AITeammateProfile.objects.filter(workspace_id=workspace_id).first()

    def iter_enabled_seeds(self) -> Iterable[AITeammateProfile]:
        """Return teammate profiles that should receive scheduled runs."""
        workspace_ids: Optional[Iterable[str]] = None
        if Workspace:
            base_qs = getattr(Workspace, "_base_manager", None) or Workspace.objects
            workspace_ids = base_qs.filter(ai_teammate_enabled=True).values_list(
                "id", flat=True,
            )

        filters = {
            "is_enabled": True,
            "status": AI_TEAMMATE_STATUS_ACTIVE,
            "workspace__isnull": False,
        }
        queryset = AITeammateProfile.objects.filter(**filters)
        if workspace_ids is not None:
            queryset = queryset.filter(workspace_id__in=workspace_ids)
        else:
            queryset = queryset.filter(workspace__ai_teammate_enabled=True)
        return queryset

    def update_last_run(self, teammate: AITeammateProfile) -> None:
        teammate.last_run_at = timezone.now()
        teammate.save(update_fields=["last_run_at", "updated_at"])


def get_ai_action_service() -> AIActionService:
    return AIActionService()
