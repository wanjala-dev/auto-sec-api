"""Workspace bounded context controllers.

Consolidated controller module containing all view classes for:
- Countries
- Workspace core functionality (views, comments, preferences, operations, cards, etc.)

This module organizes views by feature area using section comments.
"""

import uuid

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    RetrieveAPIView,
)
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

from components.team.application.facades.serializer_facade import (
    TeamSerializer,
    TeamSummaryWithMembersSerializer,
)
from components.workspace.api.permissions import (
    IsWorkspaceFollowerOrMember,
)
from components.workspace.api.workspace_permissions import (
    IsOwnerOrReadOnly,
    IsUnauthenticatedOrAdminOrStaff,
)
from components.workspace.application.facades.workspace_facade import (
    ensure_workspace_follower,
)
from components.workspace.application.providers.workspace_cache_provider import (
    get_workspace_cache_provider,
)
from components.workspace.application.queries.workspace_detail_query import (
    FetchWorkspaceDetailQuery,
)
from components.workspace.application.service import WorkspaceService
from components.workspace.mappers.rest.countries_serializers import (
    CountrySerializer,
)
from components.workspace.mappers.rest.workspace_serializers import (
    ActionSerializer,
    FiltersSerializers,
    SubCategorySerializer,
    TagSerializer,
    WorkspaceCardSerializer,
    WorkspaceCategorySerializer,
    WorkspaceCommentGetSerializer,
    WorkspaceCommentSerializer,
    WorkspaceContributionMeansAssignmentSerializer,
    WorkspaceContributionsMeansSerializer,
    WorkspaceGetSerializer,
    WorkspaceOperationsSerializer,
    WorkspacePreferenceSerializer,
    WorkspacePutSerializer,
    WorkspaceSerializer,
    WorkspaceSetupStatusSerializer,
)
from infrastructure.persistence.workspaces.models import (
    Workspace,
    WorkspaceOperations,
)

CACHE_TIMEOUT = getattr(settings, "WORKSPACE_VIEW_CACHE_TIMEOUT", 60 * 5)  # 5 minutes default
_workspace_cache = get_workspace_cache_provider().build_cache()

# Cache-busting version for the workspace list + detail endpoints.
# Include this in every cache key; bump it on any workspace mutation
# so photo / cover / name changes surface everywhere the next read
# instead of hanging on the CACHE_TIMEOUT-old payload.
_WORKSPACE_CACHE_VERSION_KEY = "workspace:cache:version"


def _workspace_cache_version() -> int:
    version = _workspace_cache.get(_WORKSPACE_CACHE_VERSION_KEY)
    if version is None:
        _workspace_cache.set(_WORKSPACE_CACHE_VERSION_KEY, 1, 60 * 60 * 24 * 30)
        return 1
    return int(version)


def _bump_workspace_cache_version() -> None:
    current = _workspace_cache_version()
    _workspace_cache.set(_WORKSPACE_CACHE_VERSION_KEY, current + 1, 60 * 60 * 24 * 30)


def _request_api_version(request) -> str:
    """Resolve the API version segment for a cache key (``'v0'`` default).

    ``WorkspaceList`` / ``WorkspaceDetail`` cache the FULLY-serialized payload,
    and the v1 contract reshapes the nested budget money into C1 objects
    (decimal strings under v0). A version-blind cache key would let a v0 request
    be served a cached v1 payload (and vice versa) — intermittent cache
    poisoning that violates v0 byte-fidelity. So the resolved ``request.version``
    is a load-bearing segment of every list/detail cache key: v0 and v1 read and
    write DISJOINT keys, and a workspace mutation bumps the shared version
    counter (``_bump_workspace_cache_version``) which invalidates BOTH variants
    at once (the counter rides in every key regardless of API version).

    ``DEFAULT_VERSION='v0'`` means unversioned/legacy routes resolve to ``'v0'``;
    we coerce a missing value to ``'v0'`` defensively so the segment is never
    empty (the v0 key was unsegmented before this change — a one-time cold-cache
    repopulation, v0 output unchanged).
    """
    return getattr(request, "version", None) or "v0"


workspace_service = WorkspaceService()


# ============================================================================
# SECTION: Countries
# ============================================================================


class CountryDetails(RetrieveAPIView):
    """Retrieve a specific country by name."""

    http_method_names = ["get", "head"]
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
    )
    name = "country-detail"
    serializer_class = CountrySerializer

    def get_queryset(self):
        return workspace_service.get_all_countries()

    def get(self, request, country=None, format=None):
        try:
            country_name = self.request.query_params.get("country", None)
            country = workspace_service.get_country_by_name(country_name)
            status_code = status.HTTP_200_OK
            response = {
                "success": "true",
                "status code": status_code,
                "message": "Workspace Country fetched successfully",
                "data": [
                    {
                        "name": country.name,
                    }
                ],
            }
        except Exception as e:
            status_code = status.HTTP_400_BAD_REQUEST
            response = {
                "success": "false",
                "status code": status.HTTP_400_BAD_REQUEST,
                "message": "Country does not exists",
                "error": str(e),
            }
        return Response(response, status=status_code)


class CountryAll(RetrieveAPIView):
    """Base country retrieval view."""

    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
    )
    serializer_class = CountrySerializer

    def get_queryset(self):
        return workspace_service.get_all_countries()

    def get(self, request, country=None, format=None):
        country = country
        if country is not None:
            stall = workspace_service.get_workspaces_by_country(country)
            serializer = WorkspaceSerializer(instance=stall, many=True, context={"request": request})
            return Response({"data": serializer.data}, status=status.HTTP_200_OK)
        countries = workspace_service.get_all_countries()
        serializer = CountrySerializer(instance=countries, many=True, context={"request": request})
        x = [dict(i) for i in serializer.data]
        return Response({"data": x}, status=status.HTTP_200_OK)


@extend_schema_view(get=extend_schema(operation_id="countries_list"))
class CountryListView(CountryAll):
    """List available countries."""

    name = "country-list"


@extend_schema_view(get=extend_schema(operation_id="countries_detail"))
class CountryByNameView(CountryAll):
    """List workspaces for a specific country."""

    name = "country-by-name"


# ============================================================================
# SECTION: Workspace Core Views
# ============================================================================


class CategorySubcategoryListView(APIView):
    """View to list all categories and their subcategories."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def get(self, request, format=None):
        cache_key = f"workspace:categories:subcategories:{request.get_host()}"
        cached_payload = _workspace_cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload, status=status.HTTP_200_OK)

        categories = workspace_service.get_workspace_categories_with_subcategories()
        data = [
            {
                "id": category.id,
                "name": category.name,
                "subcategories": SubCategorySerializer(category.subcategories.all(), many=True).data,
            }
            for category in categories
        ]

        _workspace_cache.set(cache_key, data, CACHE_TIMEOUT)
        return Response(data, status=status.HTTP_200_OK)


class WorkspaceList(APIView):
    """List all workspaces with optional category filter."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "workspace-list"

    def get(self, request, category=None, **kwargs):
        # ``**kwargs`` absorbs the ``version`` URL kwarg from the ``/api/vN/``
        # mount (without it ``/api/v0/workspaces/...`` would 500). The resolved
        # API version is also a cache-key segment so a v1 payload (nested budget
        # money as C1 objects) can never be served to a v0 request, and vice
        # versa — see ``_request_api_version``.
        api_version = _request_api_version(request)
        cache_key = (
            f"workspace:list:{request.get_host()}:{category or 'all'}:{api_version}:v{_workspace_cache_version()}"
        )
        cached_payload = _workspace_cache.get(cache_key)
        if cached_payload is not None:
            return JsonResponse(cached_payload, safe=False)

        base_queryset = workspace_service.get_all_workspaces_with_relations()

        if category:
            try:
                category_obj = workspace_service.get_workspace_category_by_name(category)
                workspaces = (
                    base_queryset.filter(workspace_categories=category_obj)
                    .exclude(workspace_name__startswith="temp-workspace-")
                    .order_by("-created_at")
                    .distinct()
                )
            except Exception:
                return HttpResponse(status=404)
        else:
            workspaces = base_queryset.exclude(workspace_name__startswith="temp-workspace-").order_by("-created_at")

        serialized_data = []
        for workspace in workspaces:
            serializer = WorkspaceGetSerializer(
                workspace,
                context={"request": request, "workspace": workspace, "api_version": api_version},
            )
            serialized_data.append(dict(serializer.data))

        _workspace_cache.set(cache_key, serialized_data, CACHE_TIMEOUT)
        return JsonResponse(serialized_data, safe=False)


class PublicAiPrivacyBriefView(APIView):
    """Public reassurance content for AI privacy controls and compliance posture."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "workspace-public-ai-privacy-brief"

    def get(self, request):
        return Response(
            {
                "status": "success",
                "data": {
                    "title": "AI privacy controls and compliance overview",
                    "summary": (
                        "We use privacy-first controls for AI features, limit data exposure, "
                        "and keep organizations in control of what is shared."
                    ),
                    "privacy_controls": [
                        "Workspace-level access controls and role-based permissions",
                        "Public/private workspace boundaries respected in API and agent flows",
                        "Operational controls for notifications, workflows, and data visibility",
                        "Auditable backend events for security-sensitive operations",
                    ],
                    "data_residency": {
                        "headline": "Data residency support",
                        "body": (
                            "Customer data stays in configured infrastructure regions where possible. "
                            "For customers with specific residency requirements, deployment and storage "
                            "topology can be aligned to regional constraints."
                        ),
                    },
                    "casl_reassurance": {
                        "headline": "CASL-friendly communications posture",
                        "body": (
                            "Messaging and campaign workflows are designed to support consent-aware "
                            "operations, clear sender identity, and unsubscribe-friendly practices "
                            "in line with CASL obligations."
                        ),
                    },
                    "last_reviewed": "2026-02-28",
                },
            },
            status=status.HTTP_200_OK,
        )


class PublicAiPrivacyBriefContractView(APIView):
    """Public backend contract for AI privacy brief + auditable controls metadata."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "workspace-public-ai-privacy-brief-contract"

    def get(self, request, *args, **kwargs):
        payload = {
            "status": "success",
            "data": {
                "contract": {
                    "version": "2026-02-28",
                    "scope": "public_ai_privacy_brief",
                    "workspace_visibility": "public",
                },
                "ai_privacy_brief": {
                    "title": "AI privacy controls and compliance overview",
                    "summary": "Privacy-first controls, bounded access, and auditable backend operations.",
                    "data_residency": {
                        "supported": True,
                        "note": "Regional deployment/storage topology can be aligned to residency requirements.",
                    },
                    "casl_reassurance": {
                        "supported": True,
                        "note": "Consent-aware communication workflows support sender identity and unsubscribe-friendly practices.",
                    },
                },
                "auditable_controls_metadata": {
                    "event_family": "ai_privacy_controls",
                    "controls": [
                        {
                            "key": "workspace_visibility_boundaries",
                            "description": "Public/private workspace boundaries enforced in backend access paths.",
                            "audit_signal": "workspace_visibility_policy_enforced",
                        },
                        {
                            "key": "role_based_access",
                            "description": "Role-scoped access controls gate AI-relevant operations.",
                            "audit_signal": "rbac_scope_check",
                        },
                        {
                            "key": "notification_workflow_controls",
                            "description": "Workflow/notification actions include auditable lifecycle events.",
                            "audit_signal": "workflow_event_dispatch",
                        },
                    ],
                },
            },
        }
        return Response(payload, status=status.HTTP_200_OK)


class WorkspacePublicProfileView(APIView):
    """Public donation profile for a workspace — `/workspaces/<id>/public/`.

    Feeds the public donate page that a nonprofit shares with anonymous
    visitors. Returns only PII-safe data (name, mission, brand assets,
    description) — never owner email, staff roster, or financial detail.
    A workspace's existence is itself non-sensitive: anyone with the
    URL can hit this endpoint, just like a homepage. The dedicated
    serializer prevents a future "fields = '__all__'" refactor from
    silently leaking private data here.

    See `components/workspace/mappers/rest/public_profile_serializers.py`
    for the response contract.
    """

    permission_classes = (permissions.AllowAny,)
    name = "workspace-public-profile"

    def get(self, request, workspace_id, *args, **kwargs):
        from components.workspace.mappers.rest.public_profile_serializers import (
            WorkspacePublicProfileSerializer,
        )
        from infrastructure.persistence.workspaces.models import Workspace as _Workspace

        workspace = get_object_or_404(_Workspace, id=workspace_id)
        serializer = WorkspacePublicProfileSerializer(workspace)
        return Response(serializer.data, status=status.HTTP_200_OK)


class FiltersView(APIView):
    """View to list workspace filter options."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def get(self, request, *args, **kwargs):
        filters = workspace_service.get_filters_map()
        serializer = FiltersSerializers(filters)
        return Response(serializer.data, status=HTTP_200_OK)


class WorkspaceTagList(generics.ListAPIView):
    """List all tags."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = TagSerializer
    name = "tag-list"

    def get_queryset(self):
        return workspace_service.get_all_tags()


# ============================================================================
# SECTION: Workspace CRUD
# ============================================================================


class WorkspaceCreateView(generics.CreateAPIView):
    """Create a new workspace."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = WorkspaceSerializer
    name = "workspace-list"

    def get_queryset(self):
        return workspace_service.get_all_workspaces()

    def perform_create(self, serializer):
        workspace = serializer.save(workspace_owner=self.request.user)
        workspace_service.create_workspace(workspace=workspace, owner=self.request.user)
        # Creating a workspace completes the user's onboarding — mirrors the
        # invite-accept path (accept_workspace_invite_use_case / join_controller)
        # which already sets this. The onboarding gate keys off the profile flag,
        # NOT the workspace's own status (a fresh workspace is still "inactive"
        # until its own setup is done — a separate, in-app concern).
        user = self.request.user
        if getattr(user, "is_authenticated", False) and not user.is_onboard_complete:
            user.is_onboard_complete = True
            user.save(update_fields=["is_onboard_complete"])


class WorkspaceCreateEligibilityView(APIView):
    """Check if user can create more workspaces."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "workspace-can-create"

    def get(self, request, *args, **kwargs):
        max_workspaces = getattr(settings, "MAX_WORKSPACES_PER_OWNER", None)
        try:
            max_workspaces = int(max_workspaces) if max_workspaces is not None else None
        except (TypeError, ValueError):
            max_workspaces = None

        owned_count = workspace_service.count_workspaces_by_owner(request.user)
        can_create = True if not max_workspaces or max_workspaces <= 0 else owned_count < max_workspaces

        return Response(
            {
                "can_create_workspace": can_create,
                "owned_workspace_count": owned_count,
                "max_workspaces_per_owner": max_workspaces,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    retrieve=extend_schema(operation_id="workspace_detail_retrieve"),
)
class WorkspaceDetail(viewsets.ModelViewSet):
    """Retrieve, update, or delete a workspace."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "workspace-detail"

    @property
    def queryset(self):
        return workspace_service.get_all_workspaces_with_relations()

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return WorkspacePutSerializer
        return WorkspaceGetSerializer

    def update(self, request, *args, **kwargs):
        """
        Use WorkspacePutSerializer for validation/writes but return the full WorkspaceGetSerializer
        payload so clients can hydrate onboarding/app state consistently.
        """
        response = super().update(request, *args, **kwargs)
        _bump_workspace_cache_version()
        workspace = self.get_object()
        serializer = WorkspaceGetSerializer(workspace, context={"request": request, "workspace": workspace})
        return Response(serializer.data, status=response.status_code)

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        _bump_workspace_cache_version()
        workspace = self.get_object()
        serializer = WorkspaceGetSerializer(workspace, context={"request": request, "workspace": workspace})
        return Response(serializer.data, status=response.status_code)

    def retrieve(self, request, *args, **kwargs):
        """Workspace detail with conditional team/project/user/category includes.

        ``*args, **kwargs`` already absorb the ``version`` URL kwarg from the
        ``/api/vN/`` mount. The resolved API version is also a cache-key segment
        so a v1 payload (nested budget money as C1 objects) is never served to a
        v0 request, and vice versa — see ``_request_api_version``.
        """
        workspace = self.get_object()

        api_version = _request_api_version(request)
        include_param = request.query_params.get("include")
        include_key = "all" if include_param is None else ("none" if include_param.strip() == "" else include_param)
        cache_key = (
            f"workspace:detail:{request.get_host()}:{workspace.id}:"
            f"{include_key}:{api_version}:v{_workspace_cache_version()}"
        )
        cached_payload = _workspace_cache.get(cache_key)
        if cached_payload is not None:
            return Response(cached_payload, status=status.HTTP_200_OK)

        detail_req = FetchWorkspaceDetailQuery.parse_include_param(include_param)
        query = workspace_service.get_workspace_detail_query()
        detail = query.execute(workspace=workspace, request=detail_req)

        # Serialization stays in the controller (needs DRF request context).
        serializer = self.get_serializer(
            workspace,
            context={"request": request, "workspace": workspace, "api_version": api_version},
        )

        # Version-select the embedded project read serializer so a v1 detail
        # response carries the project's budget / budget-estimate money as C1
        # objects (and the budget datetimes as ISO-Z); v0 stays byte-identical.
        # ``api_version`` is threaded into the project serializer context so the
        # nested budget serializer (BudgetSerializerV1) is reached under v1.
        from components.project.mappers.rest.project_serializers import (
            project_get_serializer_for_version,
        )

        project_get_serializer = project_get_serializer_for_version(api_version)
        project_context = {"request": request, "api_version": api_version}

        teams_data = []
        if detail_req.include_teams:
            serializer_cls = TeamSummaryWithMembersSerializer if detail_req.include_teams_summary else TeamSerializer
            for team in detail.teams:
                team_data = dict(serializer_cls(team, context={"request": request}).data)
                if detail_req.include_projects:
                    team_data["projects"] = list(
                        project_get_serializer(
                            detail.projects_by_team.get(team.id, []),
                            many=True,
                            context=project_context,
                        ).data
                    )
                else:
                    team_data["projects"] = []
                teams_data.append(team_data)

        workspace.associated_users = detail.associated_users

        response_data = dict(serializer.data)
        response_data["teams"] = teams_data
        response_data["projects"] = (
            list(project_get_serializer(detail.workspace_projects, many=True, context=project_context).data)
            if detail_req.include_projects
            else []
        )
        response_data["transaction_categories"] = []

        _workspace_cache.set(cache_key, response_data, CACHE_TIMEOUT)
        return Response(response_data, status=status.HTTP_200_OK)


# ============================================================================
# SECTION: Workspace Categories
# ============================================================================


class WorkspaceCategoryList(generics.ListCreateAPIView):
    """List or create workspace categories."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = WorkspaceCategorySerializer
    name = "workspacecategory-list"
    filter_fields = ("name",)
    search_fields = ("^name",)
    ordering_fields = ("name",)

    def get_queryset(self):
        return workspace_service.get_all_workspace_categories()


class WorkspaceCategoryDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a workspace category."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = WorkspaceCategorySerializer
    name = "workspacecategory-detail"

    def get_queryset(self):
        return workspace_service.get_all_workspace_categories()


# ============================================================================
# SECTION: Workspace Comments
# ============================================================================


class WorkspaceCommentList(generics.ListCreateAPIView):
    """List workspace comments."""

    serializer_class = WorkspaceCommentGetSerializer
    name = "workspacecomment-list"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
    )
    filter_fields = ("id", "workspace", "comment", "created_on", "author", "likes", "dislikes")
    search_fields = ("^comment",)
    ordering_fields = (
        "id",
        "-created_on",
    )

    def get_queryset(self):
        return workspace_service.get_all_workspace_comments()


class WorkspaceCommentCreateView(generics.CreateAPIView):
    """Create a workspace comment."""

    permission_classes = (IsWorkspaceFollowerOrMember,)
    serializer_class = WorkspaceCommentSerializer
    name = "workspace-create-comment"

    def get_queryset(self):
        return workspace_service.get_all_workspace_comments()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class WorkspaceCommentAll(RetrieveAPIView):
    """Retrieve all comments for a workspace."""

    permission_classes = (IsWorkspaceFollowerOrMember,)

    @extend_schema(operation_id="workspace_comment_by_workspace_list")
    def get(self, request, workspace=None, format=None):
        workspace_id = workspace
        if workspace_id is not None:
            stall = workspace_service.get_workspace_comments_by_workspace(workspace_id)
            serializer = WorkspaceCommentGetSerializer(instance=stall, many=True, context={"request": request})
            return Response({"data": serializer.data}, status=status.HTTP_200_OK)
        stall = workspace_service.get_workspace_comments_by_workspace(request.workspace.workspace_id)
        serializer = WorkspaceCommentGetSerializer(instance=stall, many=True, context={"request": request})
        x = [dict(i) for i in serializer.data]
        return Response({"data": x}, status=status.HTTP_200_OK)


class WorkspaceCommentDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a workspace comment."""

    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
    )
    serializer_class = WorkspaceCommentSerializer
    name = "workspacecomment-detail"

    def get_queryset(self):
        return workspace_service.get_all_workspace_comments()


# ============================================================================
# SECTION: Workspace Follow
# ============================================================================


class WorkspaceFollowView(APIView):
    """Follow or unfollow workspaces."""

    permission_classes = (permissions.IsAuthenticated,)

    def _get_workspaces(self, workspace_id, workspace_ids):
        if workspace_id:
            try:
                return [workspace_service.get_workspace_by_id(uuid.UUID(str(workspace_id)))]
            except (Exception, ValueError):
                raise ValidationError({"workspace": "Workspace not found."})
        ids = workspace_ids or []
        normalized = []
        for workspace_identifier in ids:
            try:
                normalized.append(uuid.UUID(str(workspace_identifier)))
            except (TypeError, ValueError):
                continue
        if not normalized:
            raise ValidationError({"workspace": "Provide a valid workspace or list of workspace_ids."})
        workspaces = list(workspace_service.get_workspaces_by_ids(normalized))
        if not workspaces:
            raise ValidationError({"workspace": "No workspaces found for provided identifiers."})
        return workspaces

    def post(self, request, workspace=None):
        workspaces = self._get_workspaces(workspace, request.data.get("workspace_ids"))
        for item in workspaces:
            ensure_workspace_follower(item, request.user)
        return Response(
            {"status": "success", "followed": [str(item.id) for item in workspaces]},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, workspace=None):
        workspaces = self._get_workspaces(workspace, request.data.get("workspace_ids"))
        for item in workspaces:
            item.followers.remove(request.user)
        return Response(
            {"status": "success", "unfollowed": [str(item.id) for item in workspaces]},
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(operation_id="workspace_follow_by_workspace_create"),
    delete=extend_schema(operation_id="workspace_follow_by_workspace_destroy"),
)
class WorkspaceFollowByWorkspaceView(WorkspaceFollowView):
    """Workspace-scoped follow view for unique schema operation IDs."""

    name = "workspace-follow-by-workspace"


# ============================================================================
# SECTION: Teams (legacy, may be moved to team context)
# ============================================================================


class WorkspaceTeam(RetrieveAPIView):
    """List teams in a workspace."""

    def get(self, request, workspace=None, format=None):
        workspace_id = workspace
        if workspace_id is not None:
            stall = workspace_service.get_teams_by_workspace(workspace_id)
            serializer = TeamSerializer(instance=stall, many=True, context={"request": request})
            return Response({"data": serializer.data}, status=status.HTTP_200_OK)
        stall = workspace_service.get_teams_by_workspace(request.workspace.workspace_id)
        serializer = TeamSerializer(instance=stall, many=True, context={"request": request})
        x = [dict(i) for i in serializer.data]
        return Response({"data": x}, status=status.HTTP_200_OK)


class TeamList(generics.ListCreateAPIView):
    """List or create teams."""

    serializer_class = TeamSerializer
    name = "team-list"
    filter_fields = ("name",)
    search_fields = ("^name",)
    ordering_fields = ("name",)

    def get_queryset(self):
        return workspace_service.get_all_teams()


class TeamDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a team."""

    serializer_class = TeamSerializer
    name = "team-detail"

    def get_queryset(self):
        return workspace_service.get_all_teams()


# ============================================================================
# SECTION: Actions
# ============================================================================


class ActionList(generics.ListCreateAPIView):
    """List or create actions."""

    serializer_class = ActionSerializer
    name = "action-list"
    filter_fields = (
        "title",
        "created_date",
    )
    search_fields = ("^title",)
    ordering_fields = ("title",)

    def get_queryset(self):
        return workspace_service.get_all_actions()


class ActionDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete an action."""

    serializer_class = ActionSerializer
    name = "action-detail"
    permission_classes = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)

    def get_queryset(self):
        return workspace_service.get_all_actions()


class ActionWorkspaceAll(RetrieveAPIView):
    """List all actions in a workspace."""

    @extend_schema(operation_id="workspace_actions_by_workspace_list")
    def get(self, request, workspace=None, format=None):
        workspace_id = workspace
        if workspace_id is not None:
            stall = workspace_service.get_actions_by_workspace(workspace_id)
            serializer = ActionSerializer(instance=stall, many=True, context={"request": request})
            return Response({"data": serializer.data}, status=status.HTTP_200_OK)
        stall = workspace_service.get_actions_by_workspace(request.workspace.workspace_id)
        serializer = ActionSerializer(instance=stall, many=True, context={"request": request})
        x = [dict(i) for i in serializer.data]
        return Response({"data": x}, status=status.HTTP_200_OK)


# ============================================================================
# SECTION: Workspace Preferences
# ============================================================================


class WorkspacePreferencesView(APIView):
    """Manage workspace preferences."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def _get_or_create_preference(self, workspace_id):
        workspace = get_object_or_404(Workspace, id=workspace_id)
        preference, _ = workspace_service.get_or_create_workspace_preference(workspace)
        return preference

    def post(self, request):
        serializer = WorkspacePreferenceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        else:
            return Response({"status": "error", "data": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, workspace=None):
        preference = self._get_or_create_preference(workspace)
        serializer = WorkspacePreferenceSerializer(preference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data})
        else:
            return Response({"status": "error", "data": serializer.errors})

    def get(self, request, workspace=None):
        if workspace:
            preference = self._get_or_create_preference(workspace)
            serializer = WorkspacePreferenceSerializer(preference)
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        preference = workspace_service.get_all_workspace_preferences()
        serializer = WorkspacePreferenceSerializer(preference, many=True)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, workspace=None):
        preference = get_object_or_404(Workspace, id=workspace)
        preference.delete()
        return Response({"status": "success", "data": "Item Deleted"})


@extend_schema_view(
    get=extend_schema(operation_id="workspace_preferences_by_workspace_retrieve"),
    post=extend_schema(operation_id="workspace_preferences_by_workspace_create"),
    patch=extend_schema(operation_id="workspace_preferences_by_workspace_partial_update"),
    delete=extend_schema(operation_id="workspace_preferences_by_workspace_destroy"),
)
class WorkspacePreferencesByWorkspaceView(WorkspacePreferencesView):
    """Workspace-scoped preferences view for unique schema operation IDs."""

    name = "workspace-preferences-by-workspace"


# ============================================================================
# SECTION: Workspace Operations
# ============================================================================


class WorkspaceOperationsView(APIView):
    """Manage workspace operations."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def post(self, request):
        serializer = WorkspaceOperationsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        else:
            return Response({"status": "error", "data": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, *args, **kwargs):
        for each_item in request.data:
            ids = each_item["id"]
            workspace_service.bulk_update_workspace_operations([ids], each_item["checked"])
        return Response({"status": "success"})

    def patch(self, request, workspace=None, id=None):
        operations = workspace_service.get_workspace_operation_by_id(id, workspace)
        serializer = WorkspaceOperationsSerializer(operations, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data})
        else:
            return Response({"status": "error", "data": serializer.errors})

    def get(self, request, workspace=None):
        if workspace is not None:
            operations = workspace_service.get_workspace_operations_by_workspace(workspace)
            serializer = WorkspaceOperationsSerializer(instance=operations, many=True, context={"request": request})
            return Response({"data": serializer.data}, status=status.HTTP_200_OK)
        operations = workspace_service.get_all_workspace_operations()
        serializer = WorkspaceOperationsSerializer(operations, many=True)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, workspace=None, id=None):
        operations = get_object_or_404(WorkspaceOperations, workspace_followers=workspace, id=id)
        operations.delete()
        return Response({"status": "success", "data": "Item Deleted"})


@extend_schema_view(
    get=extend_schema(operation_id="workspace_operations_by_workspace_list"),
    post=extend_schema(operation_id="workspace_operations_by_workspace_create"),
    put=extend_schema(operation_id="workspace_operations_by_workspace_update"),
    patch=extend_schema(operation_id="workspace_operations_by_workspace_partial_update"),
    delete=extend_schema(operation_id="workspace_operations_by_workspace_destroy"),
)
class WorkspaceOperationsByWorkspaceView(WorkspaceOperationsView):
    """Workspace-scoped operations view for unique schema operation IDs."""

    name = "workspace-operations-by-workspace"


@extend_schema_view(
    get=extend_schema(operation_id="workspace_operations_by_workspace_detail"),
    post=extend_schema(operation_id="workspace_operations_by_workspace_detail_create"),
    put=extend_schema(operation_id="workspace_operations_by_workspace_detail_update"),
    patch=extend_schema(operation_id="workspace_operations_by_workspace_detail_partial_update"),
    delete=extend_schema(operation_id="workspace_operations_by_workspace_detail_destroy"),
)
class WorkspaceOperationsDetailView(WorkspaceOperationsView):
    """Workspace operation detail view for unique schema operation IDs."""

    name = "workspace-operations-detail"


# ============================================================================
# SECTION: Workspace Cards
# ============================================================================


class WorkspaceCardView(APIView):
    """Manage workspace cards."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def post(self, request):
        serializer = WorkspaceCardSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        else:
            return Response({"status": "error", "data": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, workspace=None):
        preference = workspace_service.get_workspace_card_by_workspace(workspace)
        serializer = WorkspaceCardSerializer(preference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data})
        else:
            return Response({"status": "error", "data": serializer.errors})

    def get(self, request, workspace=None):
        if workspace:
            preference = workspace_service.get_workspace_card_by_workspace(workspace)
            serializer = WorkspaceCardSerializer(preference)
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        preference = workspace_service.get_all_workspace_cards()
        serializer = WorkspaceCardSerializer(preference, many=True)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, workspace=None):
        preference = get_object_or_404(Workspace, id=workspace)
        preference.delete()
        return Response({"status": "success", "data": "Item Deleted"})


@extend_schema_view(
    get=extend_schema(operation_id="workspace_cards_by_workspace_retrieve"),
    post=extend_schema(operation_id="workspace_cards_by_workspace_create"),
    patch=extend_schema(operation_id="workspace_cards_by_workspace_partial_update"),
    delete=extend_schema(operation_id="workspace_cards_by_workspace_destroy"),
)
class WorkspaceCardByWorkspaceView(WorkspaceCardView):
    """Workspace-scoped workspace card view for unique schema operation IDs."""

    name = "workspace-cards-by-workspace"


# ============================================================================
# SECTION: Contribution Means
# ============================================================================


class WorkspaceContributionMeansViewSet(viewsets.ModelViewSet):
    """Manage workspace contribution means."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = WorkspaceContributionsMeansSerializer

    def get_queryset(self):
        workspace_id = self.kwargs.get("workspace")
        if workspace_id:
            return workspace_service.get_contribution_means_by_workspace(workspace_id)
        return workspace_service.get_all_contribution_means()

    def list(self, request, *args, **kwargs):
        if request.query_params.get("page") == "all":
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        workspace_id = self.kwargs.get("workspace")
        means = serializer.save()
        if workspace_id:
            workspace = get_object_or_404(Workspace, id=workspace_id)
            workspace.contribution_means.add(means)


@extend_schema_view(
    list=extend_schema(operation_id="workspace_contribution_means_by_workspace_list"),
    create=extend_schema(operation_id="workspace_contribution_means_by_workspace_create"),
)
class WorkspaceContributionMeansByWorkspaceViewSet(WorkspaceContributionMeansViewSet):
    """Workspace-scoped contribution means viewset for unique schema operation IDs."""

    pass


class WorkspaceContributionMeansAssignmentView(APIView):
    """Assign contribution means to a workspace."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def post(self, request, *args, **kwargs):
        serializer = WorkspaceContributionMeansAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace = workspace_service.get_workspace_by_id(serializer.validated_data["workspace"])
        means = workspace_service.get_contribution_means_by_ids(serializer.validated_data["means"])

        # Update the workspace with the new contribution means
        workspace.contribution_means.set(means)

        return Response(
            {
                "message": "Successfully assigned contribution means to workspace",
                "workspace_id": str(workspace.id),
                "means_assigned": [m.id for m in means],
            }
        )


# ============================================================================
# SECTION: Workspace Setup Status
# ============================================================================


class WorkspaceSetupStatusView(APIView):
    """Get workspace setup status."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def get(self, request, workspace):
        workspace_setup_query_service = workspace_service.get_workspace_setup_query_service()
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        Prefetch = _django_orm.Prefetch
        queryset = workspace_setup_query_service.annotate_setup_state(
            workspace_service.get_all_workspaces_with_relations()
        )
        workspace_obj = get_object_or_404(queryset, id=workspace)

        status_payload = workspace_setup_query_service.build_status(workspace_obj)
        serializer = WorkspaceSetupStatusSerializer(status_payload)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)


# ============================================================================
# SECTION: Workspace Join Requests (private workspace access flow)
# ============================================================================


def _build_join_request_store():
    """Build the ORM-backed join request port.

    Kept as a factory so tests can swap in a fake port without importing
    the ORM adapter.
    """
    from components.workspace.application.providers.workspace_join_request_provider import (
        get_workspace_join_request_provider,
    )

    return get_workspace_join_request_provider().build_store()


def _serialize_join_request(result) -> dict:
    return {
        "id": result.request_id,
        "workspace_id": result.workspace_id,
        "workspace_name": result.workspace_name,
        "requester_id": result.requester_id,
        "requester_name": result.requester_name,
        "requester_email": result.requester_email,
        "status": result.status,
        "message": result.message,
        "requested_at": result.requested_at,
        "reviewed_at": result.reviewed_at,
        "reviewed_by_id": result.reviewed_by_id,
        "reviewed_by_name": result.reviewed_by_name,
        "review_note": result.review_note,
        "membership_id": result.membership_id,
    }


def _join_request_error_response(exc):
    """Map domain errors to HTTP responses."""
    from components.workspace.domain.errors import (
        JoinRequestAlreadyExistsError,
        JoinRequestNotFoundError,
        JoinRequestPermissionError,
        JoinRequestValidationError,
        WorkspaceNotFoundError,
    )

    if isinstance(exc, JoinRequestPermissionError):
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, JoinRequestAlreadyExistsError):
        return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
    if isinstance(exc, (JoinRequestNotFoundError, WorkspaceNotFoundError)):
        return Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, JoinRequestValidationError):
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return None


class WorkspaceJoinRequestListCreateView(APIView):
    """``POST /workspaces/{workspace_id}/join-requests/``

    User asks to join a private workspace.

    ``GET /workspaces/{workspace_id}/join-requests/`` lists pending
    requests for owners/admins to review.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, workspace_id):
        from components.workspace.application.ports.workspace_join_request_port import (
            CreateJoinRequestCommand,
        )
        from components.workspace.application.use_cases.create_workspace_join_request_use_case import (
            CreateWorkspaceJoinRequestUseCase,
        )

        message = (request.data.get("message") or "").strip()
        command = CreateJoinRequestCommand(
            workspace_id=str(workspace_id),
            requester_id=str(request.user.id),
            message=message,
        )
        use_case = CreateWorkspaceJoinRequestUseCase(store=_build_join_request_store())
        try:
            result = use_case.execute(command)
        except Exception as exc:
            mapped = _join_request_error_response(exc)
            if mapped is not None:
                return mapped
            raise
        return Response(_serialize_join_request(result), status=status.HTTP_201_CREATED)

    def get(self, request, workspace_id):
        store = _build_join_request_store()
        try:
            listing = store.list_pending_for_workspace(
                workspace_id=str(workspace_id),
                actor_id=str(request.user.id),
                actor_is_staff=bool(getattr(request.user, "is_staff", False)),
                actor_is_superuser=bool(getattr(request.user, "is_superuser", False)),
            )
        except Exception as exc:
            mapped = _join_request_error_response(exc)
            if mapped is not None:
                return mapped
            raise
        return Response(
            {
                "count": listing.total,
                "results": [_serialize_join_request(r) for r in listing.items],
            },
            status=status.HTTP_200_OK,
        )


class MyWorkspaceJoinRequestsView(APIView):
    """``GET /workspaces/join-requests/mine/`` — requests the caller has made."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        store = _build_join_request_store()
        listing = store.list_mine(requester_id=str(request.user.id))
        return Response(
            {
                "count": listing.total,
                "results": [_serialize_join_request(r) for r in listing.items],
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceJoinRequestManageView(APIView):
    """``POST /workspaces/join-requests/{request_id}/{action}/``

    ``action`` is one of ``approve``, ``deny``, ``withdraw``.
    Approve/deny require owner/admin; withdraw requires requester.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, request_id, action):
        from components.workspace.application.ports.workspace_join_request_port import (
            ReviewJoinRequestCommand,
            WithdrawJoinRequestCommand,
        )
        from components.workspace.application.use_cases.review_workspace_join_request_use_case import (
            ApproveWorkspaceJoinRequestUseCase,
            DenyWorkspaceJoinRequestUseCase,
            WithdrawWorkspaceJoinRequestUseCase,
        )

        action = (action or "").lower().strip()
        if action not in {"approve", "deny", "withdraw"}:
            return Response(
                {"error": "Action must be 'approve', 'deny', or 'withdraw'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = (request.data.get("note") or "").strip()
        store = _build_join_request_store()
        try:
            if action == "approve":
                command = ReviewJoinRequestCommand(
                    request_id=str(request_id),
                    reviewer_id=str(request.user.id),
                    reviewer_is_staff=bool(getattr(request.user, "is_staff", False)),
                    reviewer_is_superuser=bool(getattr(request.user, "is_superuser", False)),
                    note=note,
                )
                result = ApproveWorkspaceJoinRequestUseCase(store=store).execute(command)
            elif action == "deny":
                command = ReviewJoinRequestCommand(
                    request_id=str(request_id),
                    reviewer_id=str(request.user.id),
                    reviewer_is_staff=bool(getattr(request.user, "is_staff", False)),
                    reviewer_is_superuser=bool(getattr(request.user, "is_superuser", False)),
                    note=note,
                )
                result = DenyWorkspaceJoinRequestUseCase(store=store).execute(command)
            else:
                command = WithdrawJoinRequestCommand(
                    request_id=str(request_id),
                    actor_id=str(request.user.id),
                )
                result = WithdrawWorkspaceJoinRequestUseCase(store=store).execute(command)
        except Exception as exc:
            mapped = _join_request_error_response(exc)
            if mapped is not None:
                return mapped
            raise

        return Response(_serialize_join_request(result), status=status.HTTP_200_OK)
