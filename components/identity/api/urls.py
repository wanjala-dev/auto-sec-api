from django.urls import include, path
from rest_framework import routers

from components.identity.api.controller import (
    ChangePasswordView,
    GoogleSocialAuthView,
    ListWorkspaces,
    LoginAPIView,
    LogoutAPIView,
    MagicLinkRequestView,
    MagicLinkVerifyView,
    MyLoginActivityView,
    MySessionRevokeView,
    MySessionsRevokeOthersView,
    MySessionsView,
    PasswordTokenCheckAPI,
    ProfileEditView,
    RegisterView,
    RequestPasswordResetEmail,
    ResendVerificationEmailView,
    SessionAwareTokenRefreshView,
    SetNewPasswordAPIView,
    SignupAPI,
    StaticCreateView,
    StaticVerifyView,
    SupportImpersonationSessionEndView,
    SupportImpersonationSessionView,
    TOTPCreateView,
    TOTPDeleteView,
    TOTPVerifyView,
    UserDetails,
    UserPatchView,
    UserSummaryView,
    UserViewSet,
    VerifyEmail,
    WorkspaceAuditLogSettingsView,
    WorkspaceLoginActivityDeleteView,
    WorkspaceLoginActivityView,
    WorkspaceSessionsView,
)

router = routers.DefaultRouter()
router.register(r"users", UserViewSet, basename="users")

urlpatterns = [
    path("", include(router.urls)),
    path("detail/<str:id>/", UserDetails.as_view(), name=UserDetails.name),
    path("me/summary/", UserSummaryView.as_view(), name=UserSummaryView.name),
    path("me/sessions/", MySessionsView.as_view(), name=MySessionsView.name),
    path(
        "me/sessions/revoke-others/",
        MySessionsRevokeOthersView.as_view(),
        name=MySessionsRevokeOthersView.name,
    ),
    path(
        "me/sessions/<uuid:session_id>/",
        MySessionRevokeView.as_view(),
        name=MySessionRevokeView.name,
    ),
    path("me/login-activity/", MyLoginActivityView.as_view(), name=MyLoginActivityView.name),
    path(
        "me/impersonation-sessions/",
        SupportImpersonationSessionView.as_view(),
        name=SupportImpersonationSessionView.name,
    ),
    path(
        "me/impersonation-sessions/<uuid:session_id>/",
        SupportImpersonationSessionEndView.as_view(),
        name=SupportImpersonationSessionEndView.name,
    ),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginAPIView.as_view(), name="login"),
    path(
        "magic-link/request/",
        MagicLinkRequestView.as_view(),
        name=MagicLinkRequestView.name,
    ),
    path(
        "magic-link/verify/",
        MagicLinkVerifyView.as_view(),
        name=MagicLinkVerifyView.name,
    ),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
    # POST invitations/ removed — an unauthenticated user-enumeration oracle
    # that also returned any email's pending invitations. Clients use
    # /membership/invitations/. See the controller for the full note.
    path("email-verify/", VerifyEmail.as_view(), name="email-verify"),
    path(
        "resend-verification/",
        ResendVerificationEmailView.as_view(),
        name=ResendVerificationEmailView.name,
    ),
    # Session-aware: stock simplejwt refresh + best-effort UserSession touch.
    path("token/refresh/", SessionAwareTokenRefreshView.as_view(), name="token_refresh"),
    path("request-reset-email/", RequestPasswordResetEmail.as_view(), name="request-reset-email"),
    path("password-reset/<uidb64>/<token>/", PasswordTokenCheckAPI.as_view(), name="password-reset-confirm"),
    path("password-reset-complete", SetNewPasswordAPIView.as_view(), name="password-reset-complete"),
    path("changepassword/", ChangePasswordView.as_view(), name="change-password"),
    path("signupapi/", SignupAPI.as_view()),
    path("profile/<str:uuid>/", ProfileEditView.as_view(), name="user-profile-edit"),
    path("edit/<str:uuid>/", UserPatchView.as_view(), name="user-base-edit"),
    # OTP endpoints
    path("otp/create/", TOTPCreateView.as_view(), name="totp-create"),
    path("otp/verify/", TOTPVerifyView.as_view(), name="totp-verify"),
    path("otp/verify/<str:token>/", TOTPVerifyView.as_view(), name="totp-verify-legacy"),
    path("otp/delete/", TOTPDeleteView.as_view(), name="totp-delete"),
    path("otp/static/create/", StaticCreateView.as_view(), name="static-create"),
    path("otp/static/verify/", StaticVerifyView.as_view(), name="static-verify"),
    path("otp/static/verify/<str:token>/", StaticVerifyView.as_view(), name="static-verify-legacy"),
    # Org-level login activity + sessions (T2-S4) — admin-only. Must sit
    # before the catch-all "workspaces/<str:pk>/" route.
    path(
        "workspaces/<uuid:workspace_id>/login-activity/",
        WorkspaceLoginActivityView.as_view(),
        name=WorkspaceLoginActivityView.name,
    ),
    path(
        # AuthAuditEvent uses Django's default integer PK — int, not uuid.
        "workspaces/<uuid:workspace_id>/login-activity/<int:event_id>/",
        WorkspaceLoginActivityDeleteView.as_view(),
        name=WorkspaceLoginActivityDeleteView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/sessions/",
        WorkspaceSessionsView.as_view(),
        name=WorkspaceSessionsView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/audit-log-settings/",
        WorkspaceAuditLogSettingsView.as_view(),
        name=WorkspaceAuditLogSettingsView.name,
    ),
    path("workspaces/<str:pk>/", ListWorkspaces.as_view(), name="workspace-list"),
    # There is deliberately NO user-directory route on identity.
    #
    # ``search/`` (UserSearch) and ``search/<query>/`` (UserSearchByQuery) used
    # to live here, alongside the router's ``users/`` list. #414 found all of
    # them answering 200 with no credentials — an anonymous, cross-tenant
    # account-existence oracle — and shut them with auth + tenant scoping. A
    # caller inventory across both repos then found nothing calling either one:
    # the frontend's ``USERS_URL`` is defined and never imported, and its
    # ``userSearch`` chain dead-ends in the profile context with no consumer.
    #
    # So they are gone rather than merely gated. Person lookup has ONE home,
    # and it is the membership context, which is where the tenancy predicate
    # and the live people-pickers already are:
    #   * ``/membership/members/``      — the workspace roster
    #   * ``/membership/users/search/`` — the typeahead
    # Both are authenticated and scoped through
    # ``IdentityService.get_users_visible_to``. Route a new people surface at
    # those; do not resurrect an identity-side directory.
    # Social auth
    path("google/", GoogleSocialAuthView.as_view()),
]
