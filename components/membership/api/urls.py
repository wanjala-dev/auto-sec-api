"""URL configuration for the membership bounded context.

Mounted at ``/membership/`` in the root URL configuration.
"""

from django.urls import path

from components.membership.api.controller import (
    AcceptInvitationView,
    InvitationView,
    MembersView,
    PendingInvitationsView,
    PersonaInviteView,
    PersonaInviteAcceptView,
    PersonaInviteInfoView,
    PersonaInviteManageView,
    WorkspaceUserSearchView,
)
from components.membership.api.join_controller import (
    JoinContextController,
    JoinRegisterController,
    JoinRelationshipController,
    WorkspacePublicProfileController,
)

app_name = "membership"

urlpatterns = [
    # ── Invitations ─────────────────────────────────────────────────
    path(
        "invitations/",
        InvitationView.as_view(),
        name=InvitationView.name,
    ),
    path(
        "invitations/accept/",
        AcceptInvitationView.as_view(),
        name=AcceptInvitationView.name,
    ),
    path(
        "invitations/pending/",
        PendingInvitationsView.as_view(),
        name=PendingInvitationsView.name,
    ),
    # ── Persona-aware invite (ADR 0002) ─────────────────────────────
    path(
        "invitations/persona/",
        PersonaInviteView.as_view(),
        name=PersonaInviteView.name,
    ),
    path(
        "invitations/persona/accept/",
        PersonaInviteAcceptView.as_view(),
        name=PersonaInviteAcceptView.name,
    ),
    path(
        "invitations/persona/info/",
        PersonaInviteInfoView.as_view(),
        name=PersonaInviteInfoView.name,
    ),
    # Invitation pk is BigAutoField (see infrastructure/persistence/team/
    # models.py::Invitation) — must NOT use <uuid:>; that would 404 every
    # cancel/resend call from the Directories invitations tab.
    path(
        "invitations/persona/<int:invitation_id>/<str:action>/",
        PersonaInviteManageView.as_view(),
        name=PersonaInviteManageView.name,
    ),
    # ── Workspace-scoped user search (for invite typeahead) ────────
    path(
        "users/search/",
        WorkspaceUserSearchView.as_view(),
        name=WorkspaceUserSearchView.name,
    ),
    # ── Members ─────────────────────────────────────────────────────
    path(
        "members/",
        MembersView.as_view(),
        name=MembersView.name,
    ),
    # ── Public join (contextual invite links) ──────────────────────
    path(
        "join/workspace/<str:workspace_id>/",
        WorkspacePublicProfileController.as_view(),
        name="join-workspace-profile",
    ),
    path(
        "join/context/<str:workspace_id>/<str:context>/<str:target_id>/",
        JoinContextController.as_view(),
        name="join-context-info",
    ),
    path(
        "join/register/",
        JoinRegisterController.as_view(),
        name="join-register",
    ),
    # Authenticated self-service relationship join (onboarding "support an org").
    path(
        "join/relationship/",
        JoinRelationshipController.as_view(),
        name="join-relationship",
    ),
]
