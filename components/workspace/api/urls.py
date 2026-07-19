"""Workspace bounded context URL routing.

Consolidated URL patterns for:
- Workspace core (CRUD, list, filters, AI privacy, etc.)
- Workspace categories, comments, follow, preferences, operations, cards
- Countries
- Contribution means
- Actions

Cross-context includes:
- Workflow endpoints delegated to components.workflow.api.urls
"""

from django.urls import include, path

from components.membership.api.groups_controller import (
    WorkspaceGroupDetailView,
    WorkspaceGroupListCreateView,
    WorkspaceGroupMemberRemoveView,
    WorkspaceGroupMembersView,
    WorkspaceMemberRoleView,
    WorkspaceMembersEffectivePermissionsView,
    WorkspaceMyPermissionsView,
    WorkspacePermissionBulkView,
    WorkspacePermissionListCreateView,
    WorkspacePermissionRevokeView,
)
from components.payments.api.urls import billing_urlpatterns
from components.workspace.api.controller import (
    ActionDetail,
    ActionList,
    ActionWorkspaceAll,
    CategorySubcategoryListView,
    MyWorkspaceJoinRequestsView,
    PublicAiPrivacyBriefContractView,
    PublicAiPrivacyBriefView,
    WorkspaceCardByWorkspaceView,
    WorkspaceCardView,
    WorkspaceCategoryDetail,
    WorkspaceCategoryList,
    WorkspaceCommentAll,
    WorkspaceCommentCreateView,
    WorkspaceCommentDetail,
    WorkspaceCommentList,
    WorkspaceContributionMeansAssignmentView,
    WorkspaceContributionMeansByWorkspaceViewSet,
    WorkspaceContributionMeansViewSet,
    WorkspaceCreateEligibilityView,
    WorkspaceCreateView,
    WorkspaceDetail,
    WorkspaceFollowByWorkspaceView,
    WorkspaceFollowView,
    WorkspaceJoinRequestListCreateView,
    WorkspaceJoinRequestManageView,
    WorkspaceList,
    WorkspaceOperationsByWorkspaceView,
    WorkspaceOperationsDetailView,
    WorkspaceOperationsView,
    WorkspacePreferencesByWorkspaceView,
    WorkspacePreferencesView,
    WorkspacePublicProfileView,
    WorkspaceSetupStatusView,
    WorkspaceTagList,
)

urlpatterns = [
    # ========================================================================
    # Workspace Core
    # ========================================================================
    path("", WorkspaceList.as_view(), name=WorkspaceList.name),
    path("create/", WorkspaceCreateView.as_view(), name=WorkspaceCreateView.name),
    path("can-create/", WorkspaceCreateEligibilityView.as_view(), name="workspace-can-create"),
    path("category/<str:category>/", WorkspaceList.as_view(), name=WorkspaceList.name),
    path("tags/", WorkspaceTagList.as_view(), name=WorkspaceTagList.name),
    path(
        "public/ai-privacy-brief/contract/",
        PublicAiPrivacyBriefContractView.as_view(),
        name=PublicAiPrivacyBriefContractView.name,
    ),
    path("public/ai-privacy-brief/", PublicAiPrivacyBriefView.as_view(), name=PublicAiPrivacyBriefView.name),
    path("<uuid:workspace_id>/public/", WorkspacePublicProfileView.as_view(), name=WorkspacePublicProfileView.name),
    # ========================================================================
    # Workspace Categories
    # ========================================================================
    path("category/", WorkspaceCategoryList.as_view(), name=WorkspaceCategoryList.name),
    path("category/detail/<int:pk>/", WorkspaceCategoryDetail.as_view(), name=WorkspaceCategoryDetail.name),
    path("categories-subcategories/", CategorySubcategoryListView.as_view(), name="categories-subcategories"),
    # ========================================================================
    # Workspace Preferences
    # ========================================================================
    path(
        "<uuid:workspace>/preferences/",
        WorkspacePreferencesByWorkspaceView.as_view(),
    ),
    path(
        "preferences/",
        WorkspacePreferencesView.as_view(),
    ),
    path("<uuid:workspace>/setup-status/", WorkspaceSetupStatusView.as_view(), name="workspace-setup-status"),
    # ========================================================================
    # Workspace Join Requests (private-workspace access flow)
    # ========================================================================
    path(
        "join-requests/mine/",
        MyWorkspaceJoinRequestsView.as_view(),
        name="workspace-join-requests-mine",
    ),
    path(
        "join-requests/<uuid:request_id>/<str:action>/",
        WorkspaceJoinRequestManageView.as_view(),
        name="workspace-join-request-manage",
    ),
    path(
        "<uuid:workspace_id>/join-requests/",
        WorkspaceJoinRequestListCreateView.as_view(),
        name="workspace-join-requests",
    ),
    # ========================================================================
    # Workspace Operations
    # ========================================================================
    path(
        "<uuid:workspace>/operations/",
        WorkspaceOperationsByWorkspaceView.as_view(),
    ),
    path(
        "<uuid:workspace>/operations/<int:id>",
        WorkspaceOperationsDetailView.as_view(),
    ),
    path(
        "operations/",
        WorkspaceOperationsView.as_view(),
    ),
    # ========================================================================
    # Workspace Cards
    # ========================================================================
    path(
        "<uuid:workspace>/cards/",
        WorkspaceCardByWorkspaceView.as_view(),
    ),
    path(
        "cards/",
        WorkspaceCardView.as_view(),
    ),
    # ========================================================================
    # Actions
    # ========================================================================
    path("actions/", ActionList.as_view(), name=ActionList.name),
    path("actions/<int:pk>/", ActionDetail.as_view(), name=ActionDetail.name),
    path("<uuid:workspace>/actions/", ActionWorkspaceAll.as_view(), name="action-workspace"),
    # ========================================================================
    # Contribution Means
    # ========================================================================
    path(
        "assign-contribution-means/",
        WorkspaceContributionMeansAssignmentView.as_view(),
        name="assign-contribution-means",
    ),
    path(
        "contribution-means/",
        WorkspaceContributionMeansViewSet.as_view({"get": "list", "post": "create"}),
        name="contribution-means-list",
    ),
    path(
        "contribution-means/<int:pk>/",
        WorkspaceContributionMeansViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="contribution-means-detail",
    ),
    path(
        "<uuid:workspace>/contribution-means/",
        WorkspaceContributionMeansByWorkspaceViewSet.as_view({"get": "list", "post": "create"}),
        name="workspace-contribution-means",
    ),
    # ========================================================================
    # Workspace Follow
    # ========================================================================
    path("follow/", WorkspaceFollowView.as_view(), name="workspace-follow-batch"),
    path("<uuid:workspace>/follow/", WorkspaceFollowByWorkspaceView.as_view(), name="workspace-follow"),
    # ========================================================================
    # Workspace Detail (CRUD)
    # ========================================================================
    path(
        "<str:pk>/",
        WorkspaceDetail.as_view(
            {"get": "retrieve", "patch": "partial_update", "put": "update", "delete": "destroy", "options": "options"}
        ),
        name=WorkspaceDetail.name,
    ),
    # ========================================================================
    # Workspace Comments
    # ========================================================================
    path("comment", WorkspaceCommentList.as_view(), name=WorkspaceCommentList.name),
    path("comment/create", WorkspaceCommentCreateView.as_view(), name=WorkspaceCommentCreateView.name),
    path("comment/<int:pk>/", WorkspaceCommentDetail.as_view(), name=WorkspaceCommentDetail.name),
    path(
        "<uuid:workspace>/comment/",
        WorkspaceCommentAll.as_view(),
    ),
    # ========================================================================
    # Workspace Groups & Permissions
    # ========================================================================
    path("<uuid:workspace_id>/groups/", WorkspaceGroupListCreateView.as_view(), name="workspace-group-list-create"),
    path(
        "<uuid:workspace_id>/groups/<uuid:group_id>/", WorkspaceGroupDetailView.as_view(), name="workspace-group-detail"
    ),
    path(
        "<uuid:workspace_id>/groups/<uuid:group_id>/members/",
        WorkspaceGroupMembersView.as_view(),
        name="workspace-group-members",
    ),
    path(
        "<uuid:workspace_id>/groups/<uuid:group_id>/members/<uuid:user_id>/",
        WorkspaceGroupMemberRemoveView.as_view(),
        name="workspace-group-member-remove",
    ),
    path(
        "<uuid:workspace_id>/permissions/",
        WorkspacePermissionListCreateView.as_view(),
        name="workspace-permission-list-create",
    ),
    path(
        "<uuid:workspace_id>/permissions/bulk/", WorkspacePermissionBulkView.as_view(), name="workspace-permission-bulk"
    ),
    path("<uuid:workspace_id>/permissions/my/", WorkspaceMyPermissionsView.as_view(), name="workspace-my-permissions"),
    path(
        "<uuid:workspace_id>/permissions/<uuid:grant_id>/",
        WorkspacePermissionRevokeView.as_view(),
        name="workspace-permission-revoke",
    ),
    path(
        "<uuid:workspace_id>/members/effective-permissions/",
        WorkspaceMembersEffectivePermissionsView.as_view(),
        name="workspace-members-effective-permissions",
    ),
    path(
        "<uuid:workspace_id>/members/<uuid:user_id>/role/",
        WorkspaceMemberRoleView.as_view(),
        name="workspace-member-role",
    ),
    # ========================================================================
    # Cross-Context Includes
    # ========================================================================
    # Workflow endpoints
    path("workflows/", include("components.workflow.api.urls")),
    # SaaS billing — org subscription plans, payment methods, Stripe subscription
    # webhook, billing overview/plans/history. Delegated to components.payments.
    path("payments/", include("components.payments.api.urls")),
    path("billing/", include((billing_urlpatterns, "billing"))),
]
