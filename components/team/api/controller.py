"""Team API controllers.

Team CRUD, activation, and workspace-scoped team queries.

Invitation and membership management endpoints have been extracted to
``components.membership.api.controller``.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.team.application.commands import (
    ActivateTeamContextCommand,
    ActivateWorkspaceContextCommand,
    CreateTeamCommand,
    UpdateTeamCommand,
)
from components.team.application.service import TeamService
from components.team.mappers.rest.team_serializers import (
    TeamActivateSerializer,
    TeamSerializer,
    team_serializer_for_version,
    team_summary_serializer_for_version,
)
from components.workspace.api.permissions import IsOrgOwnerOrMember

team_service = TeamService()


def _build_post_activation_summary(request):
    """Build the fresh me/summary payload for the actor after a successful
    activation, so the frontend can apply it atomically without a second
    GET /me/summary round-trip.

    Lazy-imports IdentityService + _build_user_summary_payload so this
    module stays importable in any order at startup. activate_team_for_user
    already persisted profile.active_workspace_id + active_team_id before
    we get here, so a fresh read sees the post-switch state.
    """
    from components.identity.api.controller import _build_user_summary_payload
    from components.identity.application.service import IdentityService

    actor = IdentityService().get_user_by_id(request.user.id, with_profile=True)
    if actor is None:
        return None
    return _build_user_summary_payload(actor, request)


class TeamView(APIView):
    permission_classes = (permissions.IsAuthenticatedOrReadOnly,)
    name = 'user-teams'
    serializer_class = TeamSerializer

    def get(self, request, team_id=None, workspace_id=None, team_name=None, **kwargs):
        # ``request.version`` is set by URLPathVersioning ('v0' default / 'v1'
        # under /api/v1/). It is the ONLY version branch in this view — the
        # serializer is version-selected; the use cases stay version-blind.
        version = getattr(request, "version", None)
        full_serializer_cls = team_serializer_for_version(version)
        summary_serializer_cls = team_summary_serializer_for_version(version)
        if team_id:
            try:
                team = team_service.query_team_membership().get_team_detail(
                    team_id=team_id,
                    actor_id=getattr(request.user, 'id', None),
                    is_staff=getattr(request.user, 'is_staff', False),
                    is_superuser=getattr(request.user, 'is_superuser', False),
                )
            except ValueError as exc:
                return Response(
                    {'success': False, 'message': str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except PermissionError as exc:
                return Response(
                    {'success': False, 'message': str(exc)},
                    status=status.HTTP_403_FORBIDDEN,
                )
            except ObjectDoesNotExist as exc:
                return Response(
                    {'success': False, 'message': str(exc)},
                    status=status.HTTP_404_NOT_FOUND,
                )
            serializer = full_serializer_cls(team, context={'request': request})
            return Response(
                {
                    'success': True,
                    'message': 'Team retrieved successfully',
                    'data': serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        try:
            teams, can_view_full = team_service.query_team_membership().list_workspace_teams(
                workspace_id=workspace_id,
                actor_id=getattr(request.user, 'id', None),
                team_name=team_name,
                is_staff=getattr(request.user, 'is_staff', False),
                is_superuser=getattr(request.user, 'is_superuser', False),
            )
        except ValueError as exc:
            return Response(
                {'success': False, 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {'success': False, 'message': str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        if can_view_full:
            serializer = full_serializer_cls(teams, many=True, context={'request': request})
        else:
            serializer = summary_serializer_cls(teams, many=True, context={'request': request})

        return Response(
            {'success': True, 'message': 'Teams retrieved successfully', 'data': serializer.data},
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(operation_id="team_workspace_teams_by_name_retrieve"),
)
class TeamByWorkspaceNameView(TeamView):
    """Workspace/team-name scoped view for unique schema operation IDs."""

    name = 'team-workspace-name'


class TeamActivateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = 'team-activate'
    serializer_class = TeamActivateSerializer

    def post(self, request, *args, **kwargs):
        try:
            command = ActivateTeamContextCommand(
                team_id=request.data.get('team_id'),
                actor_id=request.user.id,
                is_staff=getattr(request.user, 'is_staff', False),
                is_superuser=getattr(request.user, 'is_superuser', False),
            )
            team = team_service.activate_team_context(command)
        except ValueError as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TeamSerializer(team, context={'request': request})
        status_code = status.HTTP_200_OK
        response = {
            'success': 'true',
            'status code': status_code,
            'message': 'The team was activated',
            'data': [{
                'team': serializer.data
            }],
            'summary': _build_post_activation_summary(request),
        }
        return Response(response, status=status_code)


class WorkspaceActivateView(APIView):
    """Activate a user's first accessible team in a workspace, in one call.

    Replaces the legacy two-call frontend flow:
        GET /seeds/<workspace_id>/teams/   → list teams
        POST /team/activate/  body={team_id}  → activate the first one

    With one call:
        POST /team/workspace/activate/  body={workspace_id}

    The backend resolves the first accessible team for the actor in that
    workspace and activates it atomically. Eliminates the ~1s of visible
    latency the two sequential round-trips were adding to every workspace
    switch and closes the race window when rapid back-and-forth clicks
    fired multiple parallel activations.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = 'workspace-activate'

    def post(self, request, *args, **kwargs):
        try:
            command = ActivateWorkspaceContextCommand(
                workspace_id=request.data.get('workspace_id'),
                actor_id=request.user.id,
                is_staff=getattr(request.user, 'is_staff', False),
                is_superuser=getattr(request.user, 'is_superuser', False),
            )
            team = team_service.activate_workspace_context(command)
        except ValueError as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionError as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ObjectDoesNotExist as exc:
            return Response(
                {'success': 'false', 'message': str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ``team`` is None for a teamless activation (a workspace member
        # with no internal team — e.g. a sponsor / viewer). The workspace
        # pointer was still persisted; the response carries a null team.
        team_payload = (
            TeamSerializer(team, context={'request': request}).data
            if team is not None
            else None
        )
        status_code = status.HTTP_200_OK
        return Response(
            {
                'success': 'true',
                'status code': status_code,
                'message': 'The workspace was activated',
                'data': [{'team': team_payload}],
                'summary': _build_post_activation_summary(request),
            },
            status=status_code,
        )


class TeamAddView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = 'workspace-team'
    serializer_class = TeamSerializer

    def get_permissions(self):
        if getattr(self.request, "method", "").upper() == 'POST':
            return [permissions.IsAuthenticated(), IsOrgOwnerOrMember()]
        return [permissions.IsAuthenticated()]

    def get(self, request, uuid=None):
        try:
            teams = team_service.query_team_membership().list_user_teams(
                actor_id=request.user.id,
                user_id=uuid,
                is_staff=getattr(request.user, 'is_staff', False),
                is_superuser=getattr(request.user, 'is_superuser', False),
            )
        except PermissionError as exc:
            status_code = status.HTTP_401_UNAUTHORIZED if str(exc) == 'Authentication required.' else status.HTTP_403_FORBIDDEN
            return Response({"status": "error", "message": str(exc)}, status=status_code)
        serializer = TeamSerializer(teams, many=True, context={'request': request})
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        try:
            command = CreateTeamCommand(
                title=request.data.get('title'),
                # 'workspace' is canonical; 'seed' is the legacy alias older
                # clients (and the pre-fix Teams index) send. Plan is derived
                # server-side from the workspace — client input is ignored.
                workspace_id=request.data.get('workspace') or request.data.get('seed'),
                actor=request.user,
            )
            team = team_service.create_team(command)
        except ValueError as exc:
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            status_code = status.HTTP_401_UNAUTHORIZED if str(exc) == 'Authentication required.' else status.HTTP_403_FORBIDDEN
            return Response({"status": "error", "message": str(exc)}, status=status_code)

        serializer = TeamSerializer(team, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request, uuid=None):
        serializer = TeamSerializer(data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return Response({"status": "error", "data": serializer.errors})

        try:
            command = UpdateTeamCommand(
                actor=request.user,
                validated_data=serializer.validated_data,
                is_staff=getattr(request.user, 'is_staff', False),
                is_superuser=getattr(request.user, 'is_superuser', False),
            )
            team = team_service.update_team(command)
        except PermissionError as exc:
            status_code = status.HTTP_401_UNAUTHORIZED if str(exc) == 'Authentication required.' else status.HTTP_403_FORBIDDEN
            return Response({"status": "error", "message": str(exc)}, status=status_code)
        except ObjectDoesNotExist as exc:
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"status": "success", "data": TeamSerializer(team, context={'request': request}).data})


@extend_schema_view(
    get=extend_schema(operation_id="team_by_user_retrieve"),
    post=extend_schema(operation_id="team_by_user_create"),
    patch=extend_schema(operation_id="team_by_user_partial_update"),
)
class TeamAddByUuidView(TeamAddView):
    """User-scoped team view for unique schema operation IDs."""

    name = 'workspace-team-by-user'



# ── Invitation and membership views have been extracted to ────────────
# ``components.membership.api.controller``.
# The following endpoints now live at /membership/:
#   POST /membership/invitations/          (was /teams/invite/)
#   POST /membership/invitations/accept/   (was /teams/invite/accept/)
#   GET  /membership/members/              (was /teams/members/)
#   GET  /membership/invitations/pending/  (was /teams/invitations/)
