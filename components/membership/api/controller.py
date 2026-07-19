"""Membership bounded context controller.

All HTTP endpoints for membership management: invitations, members,
pending invitations.

Extracted from ``components.team.api.controller`` — the team context
retains team CRUD and activation; membership management now lives here.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.membership.application.commands import (
    AcceptInvitationCommand,
    ProcessInvitationBatchCommand,
)
from components.membership.mappers.rest.membership_serializers import (
    InvitationAcceptSerializer,
    InvitationRequestSerializer,
    MembershipSummarySerializer,
    PendingInvitationSerializer,
)
from components.membership.application.service import MembershipService

membership_service = MembershipService()


# ── Invitations ────────────────────────────────────────────────────────


class InvitationView(APIView):
    """GET  /membership/invitations/ — list pending invitations
    POST /membership/invitations/ — issue batch invitations to a team.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-invite"
    serializer_class = InvitationRequestSerializer

    def get(self, request, *args, **kwargs):
        """List pending invitations for a workspace (delegates to query service)."""
        try:
            pending_invitations = membership_service.query_membership().list_workspace_pending_invitations(
                workspace_id=(
                    request.query_params.get("workspace_id")
                    or kwargs.get("workspace_id")
                ),
                actor_id=request.user.id,
                is_staff=getattr(request.user, "is_staff", False),
                is_superuser=getattr(request.user, "is_superuser", False),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PendingInvitationSerializer(
            pending_invitations,
            many=True,
        )
        return Response(
            {
                "success": True,
                "count": len(pending_invitations),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        def error_response(message, status_code=status.HTTP_400_BAD_REQUEST):
            return Response({"error": message}, status=status_code)

        try:
            serializer = InvitationRequestSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(serializer.errors)

            data = serializer.validated_data
            emails = []
            if data.get("email"):
                emails.append(data["email"])
            emails.extend(data.get("emails") or [])
            command = ProcessInvitationBatchCommand(
                actor=request.user,
                workspace_id=data.get("workspace"),
                team_id=data.get("team"),
                emails=emails,
                user_ids=data.get("user_ids") or [],
                request=request,
                is_staff=getattr(request.user, "is_staff", False),
                is_superuser=getattr(request.user, "is_superuser", False),
            )
            result = membership_service.process_invitation_batch(command)
            return Response(
                {"success": True, "message": result.message, "results": result.results},
                status=status.HTTP_200_OK,
            )

        except PermissionError as exc:
            status_code = (
                status.HTTP_401_UNAUTHORIZED
                if str(exc) == "Authentication required."
                else status.HTTP_403_FORBIDDEN
            )
            return error_response(str(exc), status_code)
        except ObjectDoesNotExist as exc:
            return error_response(str(exc), status.HTTP_404_NOT_FOUND)
        except (ImproperlyConfigured, ValueError) as exc:
            return error_response(str(exc))
        except Exception as e:
            return error_response(str(e))


class AcceptInvitationView(APIView):
    """POST /membership/invitations/accept/

    Accept an invitation by code.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-accept-invitation"
    serializer_class = InvitationAcceptSerializer

    def post(self, request, *args, **kwargs):
        user = request.user
        try:
            command = AcceptInvitationCommand(
                code=request.data.get("code"),
                actor=user,
            )
            invitation = membership_service.accept_invitation(command)
        except ValueError as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            status_code = (
                status.HTTP_401_UNAUTHORIZED
                if str(exc) == "Authentication required."
                else status.HTTP_403_FORBIDDEN
            )
            return Response(
                {"status": "error", "message": str(exc)},
                status=status_code,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        team = invitation.team
        membership_service.invitation_notification(
            invitation=invitation,
            actor=user,
        )

        return Response(
            {
                "success": "true",
                "status code": status.HTTP_200_OK,
                "message": "Invitation accepted",
                "data": [
                    {
                        "team_id": team.id,
                        "joined_at": (
                            invitation.accepted_at.isoformat()
                            if invitation.accepted_at
                            else None
                        ),
                    }
                ],
            },
            status=status.HTTP_200_OK,
        )


# ── Members ────────────────────────────────────────────────────────────


class MembersView(APIView):
    """GET /membership/members/

    List all workspace team members.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-members"
    serializer_class = MembershipSummarySerializer

    def get(self, request, *args, **kwargs):
        try:
            members, team_lookup = membership_service.query_membership().list_workspace_team_members(
                workspace_id=(
                    request.query_params.get("workspace_id")
                    or kwargs.get("workspace_id")
                ),
                actor_id=request.user.id,
                is_staff=getattr(request.user, "is_staff", False),
                is_superuser=getattr(request.user, "is_superuser", False),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = MembershipSummarySerializer(
            members,
            many=True,
            context={"team_lookup": team_lookup, "request": request},
        )

        return Response(
            {
                "success": True,
                "count": len(members),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ── Pending invitations ───────────────────────────────────────────────


class PendingInvitationsView(APIView):
    """GET /membership/invitations/pending/

    List pending invitations for a workspace.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-pending-invitations"
    serializer_class = PendingInvitationSerializer

    def get(self, request, *args, **kwargs):
        try:
            pending_invitations = membership_service.query_membership().list_workspace_pending_invitations(
                workspace_id=(
                    request.query_params.get("workspace_id")
                    or kwargs.get("workspace_id")
                ),
                actor_id=request.user.id,
                is_staff=getattr(request.user, "is_staff", False),
                is_superuser=getattr(request.user, "is_superuser", False),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {"success": False, "message": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PendingInvitationSerializer(
            pending_invitations,
            many=True,
        )
        return Response(
            {
                "success": True,
                "count": len(pending_invitations),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ── Persona-aware invite (ADR 0002) ─────────────────────────────────────


class PersonaInviteView(APIView):
    """POST /membership/invitations/persona/

    Issue a magic-link invitation that lands the recipient on a specific
    persona's dashboard (sponsor / contributor / volunteer / auditor /
    board_member). Reuses the existing invitation table — the persona +
    role + token fields drive the accept flow.

    Permission: workspace owner / admin (RBAC role only — never persona).
    See ADR 0002.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-persona-invite"

    def post(self, request, *args, **kwargs):
        from components.team.application.use_cases.create_workspace_invite_use_case import (
            CreateWorkspaceInviteCommand,
            CreateWorkspaceInviteUseCase,
        )

        user = request.user
        command = CreateWorkspaceInviteCommand(
            workspace_id=request.data.get("workspace_id"),
            email=request.data.get("email") or "",
            persona=(request.data.get("persona") or "").strip().lower(),
            inviter_user_id=str(user.id) if user and user.is_authenticated else None,
            inviter_is_staff=bool(getattr(user, "is_staff", False)),
            inviter_is_superuser=bool(getattr(user, "is_superuser", False)),
            role=request.data.get("role"),
            team_id=request.data.get("team_id"),
            display_name=request.data.get("display_name"),
            photo_url=request.data.get("photo_url"),
            permission_group_ids=request.data.get("permission_group_ids") or [],
        )
        use_case = CreateWorkspaceInviteUseCase()
        result = use_case.execute(command)
        if result.error is not None:
            return Response({"error": result.error}, status=result.status_code)
        return Response(result.payload, status=result.status_code)


class PersonaInviteManageView(APIView):
    """POST /membership/invitations/persona/<invitation_id>/<action>/

    Admin actions on a pending invitation. Two actions are supported:

    - ``resend`` mints a fresh magic-link token, bumps the expiry to 24h
      from now, flips status back to ``invited`` (in case the row was
      stuck on ``expired`` / ``accepted``), and returns the new token
      payload so the frontend can show the copy-link UI immediately.
    - ``cancel`` flips the row to ``revoked`` so the magic link stops
      working. Idempotent — calling it on an already-revoked row is a
      no-op.

    Permission: workspace owner or admin (RBAC role only — never persona).
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-persona-invite-manage"

    def post(self, request, invitation_id=None, action=None, *args, **kwargs):
        import secrets
        from datetime import timedelta
        from django.utils import timezone
        from components.team.application.providers.team_models_provider import (
            get_team_models_provider,
        )
        _pkg_models = get_team_models_provider()
        Invitation = _pkg_models.Invitation
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )
        _pkg_models = get_workspaces_models_provider()
        Workspace = _pkg_models.Workspace
        WorkspaceMembership = _pkg_models.WorkspaceMembership

        if action not in ("resend", "cancel"):
            return Response(
                {"error": "Action must be 'resend' or 'cancel'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation = Invitation.objects.filter(id=invitation_id).first()
        if invitation is None:
            return Response(
                {"error": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # RBAC: workspace owner or admin (or staff/superuser).
        user = request.user
        is_authorized = (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or Workspace.objects.filter(
                id=invitation.workspace_id, workspace_owner_id=user.id
            ).exists()
            or WorkspaceMembership.objects.filter(
                workspace_id=invitation.workspace_id,
                user_id=user.id,
                status=WorkspaceMembership.Status.ACTIVE,
                role__in=(
                    WorkspaceMembership.Role.OWNER,
                    WorkspaceMembership.Role.ADMIN,
                ),
            ).exists()
        )
        if not is_authorized:
            return Response(
                {"error": "Only workspace owners or admins can manage invitations."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if action == "cancel":
            invitation.status = Invitation.REVOKED
            invitation.save(update_fields=["status"])
            return Response(
                {
                    "invitation_id": str(invitation.id),
                    "status": invitation.status,
                },
                status=status.HTTP_200_OK,
            )

        # Resend — mint a new token, bump expiry, flip status back to invited.
        new_token = secrets.token_hex(32)
        invitation.token = new_token
        invitation.code = new_token[:20]
        invitation.expires_at = timezone.now() + timedelta(hours=24)
        invitation.status = Invitation.INVITED
        invitation.accepted_at = None
        invitation.save(
            update_fields=[
                "token",
                "code",
                "expires_at",
                "status",
                "accepted_at",
            ]
        )

        # Re-fire the email so the recipient gets a fresh link in their inbox.
        try:
            from components.team.application.providers.invitation_email_provider import (
                get_invitation_email_provider,
            )
            send_persona_invitation = get_invitation_email_provider().send_persona_invitation
            send_persona_invitation(invitation, inviter_user=user)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("invitations").exception(
                "persona invite resend email failed for %s",
                invitation.email,
            )

        return Response(
            {
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "expires_at": invitation.expires_at,
                "token": new_token,
            },
            status=status.HTTP_200_OK,
        )


class PersonaInviteAcceptView(APIView):
    """POST /membership/invitations/persona/accept/

    Magic-link accept. The token IS the credential; this endpoint is
    intentionally unauthenticated. Body: {token, password?, first_name?,
    last_name?}. Returns JWT access/refresh tokens on success so the
    frontend signs the user straight in.

    ``password`` is optional when the invitee already has an established
    account — in that case the existing credential stays in place.
    """

    permission_classes = (permissions.AllowAny,)
    name = "membership-persona-invite-accept"

    def post(self, request, *args, **kwargs):
        from components.team.application.use_cases.accept_workspace_invite_use_case import (
            AcceptWorkspaceInviteCommand,
            AcceptWorkspaceInviteUseCase,
        )

        command = AcceptWorkspaceInviteCommand(
            token=(request.data.get("token") or "").strip(),
            password=request.data.get("password") or "",
            first_name=request.data.get("first_name"),
            last_name=request.data.get("last_name"),
        )
        result = AcceptWorkspaceInviteUseCase().execute(command)
        if result.error is not None:
            return Response({"error": result.error}, status=result.status_code)
        return Response(result.payload, status=result.status_code)


class WorkspaceUserSearchView(APIView):
    """GET /membership/users/search/?q=jane&workspace_id=<uuid>

    Typeahead support for the invite form. Returns up to 10 users that
    share at least one workspace with the requester — narrower than a
    system-wide search so admins don't leak email-existence beyond the
    workspaces they already belong to.

    Shape per result:
        {id, email, display_name, photo_url}

    The optional ``workspace_id`` is treated as a soft hint — results are
    not filtered to that workspace alone (we *want* to surface "this
    person is on Wanjala in another workspace you also belong to" so the
    inviter can pull them in). It is reserved for future ranking.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "membership-user-search"

    MAX_RESULTS = 10
    MIN_QUERY_LEN = 2

    def get(self, request, *args, **kwargs):
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )
        _django_orm = _get_django_orm_provider()
        Q = _django_orm.Q
        from components.identity.application.providers.users_models_provider import (
            get_users_models_provider,
        )
        _pkg_models = get_users_models_provider()
        CustomUser = _pkg_models.CustomUser
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )
        _pkg_models = get_workspaces_models_provider()
        WorkspaceMembership = _pkg_models.WorkspaceMembership

        query = (request.query_params.get("q") or "").strip()
        if len(query) < self.MIN_QUERY_LEN:
            return Response({"results": []}, status=status.HTTP_200_OK)

        # Workspaces the requester belongs to (active membership). Staff
        # / superuser see across the system — they're already trusted.
        actor = request.user
        if getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False):
            scoped_user_ids = None
        else:
            actor_workspace_ids = list(
                WorkspaceMembership.objects.filter(
                    user_id=actor.id,
                    status=WorkspaceMembership.Status.ACTIVE,
                ).values_list("workspace_id", flat=True)
            )
            if not actor_workspace_ids:
                return Response({"results": []}, status=status.HTTP_200_OK)
            scoped_user_ids = set(
                WorkspaceMembership.objects.filter(
                    workspace_id__in=actor_workspace_ids,
                    status=WorkspaceMembership.Status.ACTIVE,
                ).values_list("user_id", flat=True)
            )

        users = CustomUser.objects.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query),
            is_active=True,
        ).exclude(id=actor.id)

        if scoped_user_ids is not None:
            users = users.filter(id__in=scoped_user_ids)

        users = users.select_related("profile")[: self.MAX_RESULTS]

        results = []
        for user in users:
            full_name = (
                f"{user.first_name} {user.last_name}".strip()
                or user.username
                or user.email
            )
            photo_url = ""
            profile = getattr(user, "profile", None)
            if profile is not None:
                photo_url = getattr(profile, "photo_url", "") or ""
            results.append({
                "id": str(user.id),
                "email": user.email,
                "display_name": full_name,
                "photo_url": photo_url,
            })
        return Response({"results": results}, status=status.HTTP_200_OK)


class PersonaInviteInfoView(APIView):
    """GET /membership/invitations/persona/info/?token=<magic-link>

    Returns lightweight metadata about a pending magic-link invite so the
    frontend can render the right UX before the user clicks accept:
    existing established users see a one-click "Accept invitation" CTA;
    new users see the password-setup form.

    Intentionally unauthenticated — the token is the credential. Only
    metadata is returned (no PII beyond the email already known to the
    recipient who clicked the link).
    """

    permission_classes = (permissions.AllowAny,)
    name = "membership-persona-invite-info"

    def get(self, request, *args, **kwargs):
        from django.utils import timezone
        from components.team.application.providers.team_models_provider import (
            get_team_models_provider,
        )
        _pkg_models = get_team_models_provider()
        Invitation = _pkg_models.Invitation
        from components.identity.application.providers.users_models_provider import (
            get_users_models_provider,
        )
        _pkg_models = get_users_models_provider()
        CustomUser = _pkg_models.CustomUser

        token = (request.query_params.get("token") or "").strip()
        if not token:
            return Response(
                {"error": "token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation = (
            Invitation.objects
            .select_related("workspace")
            .filter(token=token)
            .first()
        )
        if invitation is None:
            return Response(
                {"error": "Invalid or expired invitation link."},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        if invitation.status != Invitation.INVITED:
            return Response(
                {"error": "This invitation has already been used or revoked."},
                status=status.HTTP_409_CONFLICT,
            )
        if invitation.expires_at and invitation.expires_at < now:
            return Response(
                {"error": "This invitation has expired."},
                status=status.HTTP_410_GONE,
            )

        user = CustomUser.objects.filter(email=invitation.email).first()
        is_existing_user = bool(user and user.has_usable_password())
        workspace = invitation.workspace
        return Response(
            {
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "workspace_id": str(invitation.workspace_id),
                "workspace_name": (
                    getattr(workspace, "workspace_name", "") or ""
                ),
                "is_existing_user": is_existing_user,
                "expires_at": (
                    invitation.expires_at.isoformat()
                    if invitation.expires_at
                    else None
                ),
            },
            status=status.HTTP_200_OK,
        )
