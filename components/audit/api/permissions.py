"""Audit-context DRF permissions.

The audit read endpoints expose field-level change history including
actor identity (name/email fallback) and previous values. That is
tenant data: only people inside the workspace may read it.

Membership (not admin) is the deliberate bar — the workspace audit
trail is a read surface for every operator in the tenant, including
the read-only auditor persona.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from components.workspace.api.permissions import IsOrgOwnerOrMember


class IsAuditWorkspaceMember(IsOrgOwnerOrMember):
    """Member-of-workspace gate for the audit read endpoints.

    Contract:

    * The request MUST carry an explicit ``workspace_id`` query param.
      Missing param → 400 (raised here as a DRF ``ValidationError`` so
      no handler can forget to validate it).
    * The caller must be the workspace owner, an ACTIVE workspace
      member, or an active team member of that workspace (the shared
      ``IsOrgOwnerOrMember._is_member`` rule). Otherwise → 403.
    * Unknown / malformed workspace ids → 403 (indistinguishable from
      "not a member" so the endpoint doesn't leak workspace existence).

    Unlike the base class, this permission deliberately does NOT honour
    the ``seed``/``seed_id`` aliases, request-body keys, or the
    active-workspace profile fallback — the tenant must be named
    explicitly on every request so the repository scoping and the
    authorization check are guaranteed to talk about the same
    workspace.
    """

    message = "You must be a member of this workspace to read its audit history."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        workspace_id = (request.query_params.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValidationError({"workspace_id": ["This query parameter is required."]})

        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        Workspace = get_workspaces_models_provider().Workspace
        try:
            workspace = Workspace.objects.filter(id=workspace_id).first()
        except (ValueError, TypeError, DjangoValidationError):
            workspace = None
        if workspace is None:
            return False

        return self._is_member(user, workspace)
