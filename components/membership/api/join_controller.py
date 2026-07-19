"""Public join endpoints for contextual invite links.

These endpoints are intentionally unauthenticated — they power the
shareable link flow where anonymous visitors can view workspace/entity
info and register as sponsors without a pre-existing invitation.
"""

from __future__ import annotations

import logging

from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)

_django_orm = _get_django_orm_provider()
transaction = _django_orm.transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

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
                "sector": (getattr(ws, "sector", None) and str(ws.sector)) or "",
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


class JoinRegisterController(APIView):
    """Register a new user and auto-join them to a workspace as sponsor.

    This is the stripped-down registration for contextual invite links.
    No invitation token required — the link IS the invitation.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        first_name = (request.data.get("first_name") or "").strip()
        last_name = (request.data.get("last_name") or "").strip()
        workspace_id = request.data.get("workspace_id")

        if not email or not password or not workspace_id:
            return Response(
                {"detail": "email, password, and workspace_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(password) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        Workspace = get_workspaces_models_provider().Workspace

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is None:
            return Response(
                {"detail": "Workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from components.identity.application.providers.users_models_provider import get_users_models_provider

        CustomUser = get_users_models_provider().CustomUser

        with transaction.atomic():
            user, created = CustomUser.objects.get_or_create(
                email=email,
                defaults={
                    "username": email.split("@")[0],
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_verified": True,
                    "is_onboard_complete": True,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            elif not user.check_password(password):
                return Response(
                    {"detail": "An account with this email already exists. Please log in instead."},
                    status=status.HTTP_409_CONFLICT,
                )

            # Update name if not set
            if first_name and not user.first_name:
                user.first_name = first_name
            if last_name and not user.last_name:
                user.last_name = last_name
            if not user.is_onboard_complete:
                user.is_onboard_complete = True
            user.save(update_fields=["first_name", "last_name", "is_onboard_complete"])

            # Ensure user profile with active workspace
            UserProfile = get_users_models_provider().UserProfile

            profile, _ = UserProfile.objects.get_or_create(user=user)
            if not getattr(profile, "active_workspace_id", None):
                profile.active_workspace_id = str(workspace.id)
                profile.save(update_fields=["active_workspace_id"])

            # Create workspace membership as sponsor. Double-write the
            # workspace_role FK alongside the legacy role string so
            # Phase 2 RBAC readers don't have to special-case public
            # sponsor sign-ups.
            from components.team.application.providers.team_models_provider import get_team_models_provider

            WorkspaceMembership = get_team_models_provider().WorkspaceMembership
            from components.workspace.application.providers.workspaces_models_provider import (
                get_workspaces_models_provider,
            )

            WorkspaceRole = get_workspaces_models_provider().WorkspaceRole

            viewer_role = WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug="viewer").first()
            membership, mem_created = WorkspaceMembership.objects.get_or_create(
                user=user,
                workspace=workspace,
                defaults={
                    "persona": "sponsor",
                    "role": "viewer",
                    "workspace_role": viewer_role,
                    "status": "active",
                },
            )
            reactivate_fields = []
            if not mem_created and membership.status != "active":
                membership.status = "active"
                reactivate_fields.append("status")
            if membership.workspace_role_id is None and viewer_role is not None:
                membership.workspace_role = viewer_role
                reactivate_fields.append("workspace_role")
            if reactivate_fields:
                membership.save(update_fields=reactivate_fields)

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user_id": str(user.id),
                "email": user.email,
                "workspace_id": str(workspace.id),
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "is_new_user": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
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
