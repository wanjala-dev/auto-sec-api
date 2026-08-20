"""Public join endpoints for contextual invite links.

The read endpoints here are intentionally unauthenticated — they power the
shareable link flow where anonymous visitors can view workspace/entity info
before deciding to join.

WRITES DO NOT BELONG HERE. This module used to carry a
``JoinRegisterController`` that created an account and signed the caller in
from an unauthenticated POST. It is gone; the two things it conflated each
already have exactly one canonical owner:

* creating an account → ``POST /identity/register/`` (password policy,
  emailed verification, login activity, throttles, lockout);
* attaching that account to a workspace → ``POST /membership/join/relationship/``
  below, which runs ``EstablishWorkspaceRelationshipUseCase`` as the
  authenticated user.

See the deletion commit for why the duplicate was a security surface and not
merely redundant.
"""

from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class WorkspacePublicProfileController(APIView):
    """Return public workspace info for the join landing page."""

    permission_classes = (permissions.AllowAny,)

    def get(self, request, workspace_id=None):
        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        Workspace = get_workspaces_models_provider().Workspace

        ws = Workspace.objects.filter(id=workspace_id).first()
        if ws is None:
            return Response(
                {"detail": "Workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "id": str(ws.id),
                "name": getattr(ws, "workspace_name", "") or "",
                "description": getattr(ws, "description", "") or "",
                "photo_url": getattr(ws, "photo_url", "") or "",
                "domains": [d.name for d in ws.domains.all()],
            }
        )


class JoinContextController(APIView):
    """Return public info about a target entity (campaign, event, recipient, project)."""

    permission_classes = (permissions.AllowAny,)

    def get(self, request, workspace_id=None, context=None, target_id=None):
        if context == "project":
            return self._project(workspace_id, target_id)
        return Response(
            {"detail": f"Unknown context: {context}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _project(self, workspace_id, target_id):
        from components.project.application.providers.project_models_provider import get_project_models_provider

        Project = get_project_models_provider().Project

        p = Project.objects.filter(id=target_id, workspace_id=workspace_id).first()
        if p is None:
            return Response({"detail": "Project not found."}, status=404)
        return Response(
            {
                "type": "project",
                "id": str(p.id),
                "name": p.title or "",
                "description": p.description or "",
                "status": getattr(p, "status", ""),
            }
        )


class JoinRelationshipController(APIView):
    """Authenticated self-service join: pick how you relate to an org.

    Used by onboarding's "support an existing organization" flow once the
    user is already logged in. Body: ``{workspace_id, relationship}`` where
    ``relationship`` is one of ``follow | sponsor | volunteer | contribute``.

    - ``follow``    → follow the workspace (no membership); FE → org profile.
    - ``sponsor``   → ACTIVE ``persona=sponsor, role=viewer`` membership;
                      FE → sponsor dashboard.
    - ``volunteer``/``contribute`` → owner-approval-gated team join. A PENDING
                      membership lands the user on the contributor dashboard
                      immediately behind a "pending approval" lock, and a join
                      request is raised for the owner to approve.

    All orchestration lives in
    ``EstablishWorkspaceRelationshipUseCase``; this controller only parses the
    request and serialises the outcome.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        from components.membership.application.providers.membership_provider import (
            MembershipProvider,
        )
        from components.membership.application.use_cases.establish_workspace_relationship_use_case import (
            EstablishWorkspaceRelationshipCommand,
        )
        from components.shared_kernel.domain.errors import (
            NotFoundError,
            ValidationError,
        )

        command = EstablishWorkspaceRelationshipCommand(
            workspace_id=request.data.get("workspace_id") or "",
            user_id=str(request.user.id),
            relationship=request.data.get("relationship") or "",
        )

        use_case = MembershipProvider().build_establish_relationship_use_case()
        try:
            outcome = use_case.execute(command)
        except NotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "relationship": outcome.relationship,
                "workspace_id": outcome.workspace_id,
                "redirect": outcome.redirect,
                "persona": outcome.persona,
                "status": outcome.status,
            },
            status=status.HTTP_200_OK,
        )
