import logging

from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from components.identity.application.service import IdentityService
from components.workspace.application.providers.user_onboarding_workspace_provider import (
    UserOnboardingWorkspaceProvider,
)


def ensure_user_workspace_context(user, *, create_if_missing=False):
    """Delegate to workspace component use case via provider."""
    if not user:
        return None
    use_case = UserOnboardingWorkspaceProvider.build_ensure_workspace_use_case()
    result = use_case.execute(user.id, create_if_missing=create_if_missing)
    if result is None:
        return None
    # Return the ORM workspace for backwards compatibility with callers
    # that expect a Workspace instance.
    service = IdentityService()
    return service.get_workspace(result.workspace_id)


from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator

# BlacklistedToken/OutstandingToken removed — token revocation now in LogoutUseCase
from django.contrib.sites.shortcuts import get_current_site
from django.http import HttpResponsePermanentRedirect
from django.utils import timezone

# Social serializers removed — social views live in social_controller.py
from django.utils.decorators import method_decorator
from django.utils.encoding import DjangoUnicodeDecodeError, smart_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status, views

# Social models removed — social views live in social_controller.py
# Notification model removed — unused
# NotificationDispatcher removed — unused module-level instance
from rest_framework.generics import GenericAPIView, RetrieveAPIView, UpdateAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from components.identity.api.permissions import (
    IsLoggedInUserOrAdmin,
    IsTwoFactorEnabledAndVerified,
    IsUnauthenticatedOrAdminOrStaff,
)
from components.identity.api.renderers import UserRenderer
from components.identity.api.request_context import build_request_context, extract_client_ip
from components.identity.api.throttles import (
    EmailVerifyThrottle,
    LoginThrottle,
    OTPVerifyThrottle,
    PasswordResetConfirmThrottle,
    PasswordResetRequestThrottle,
    StaticVerifyThrottle,
)
from components.identity.domain.enums import LOGIN_ACTIVITY_EVENT_CODES

# Also add these imports
from components.identity.mappers.rest.identity_serializers import (
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    GoogleSocialAuthSerializer,
    LoginSerializer,
    LogoutSerializer,
    RegisterSerializer,
    ResetPasswordEmailRequestSerializer,
    SetNewPasswordSerializer,
    UserPatchSerializer,
    UserProfileSerializer,
    UserSerializer,
    UserSerializerUUID,
    UserSummarySerializer,
)
from components.identity.mappers.rest.otp_serializers import PasswordConfirmSerializer
from components.identity.mappers.rest.session_serializers import (
    LoginActivityEventSerializer,
    MySessionSerializer,
    OrgAuditLogSettingsSerializer,
    WorkspaceLoginActivityEventSerializer,
    WorkspaceSessionSerializer,
)
from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.workspace.api.permissions import IsWorkspaceAdmin

logger = logging.getLogger(__name__)
import uuid

# ObjectDoesNotExist, ValidationError removed — no longer used after query extraction
from components.shared_platform.mappers.rest.core_serializers import EmptySerializer, WorkspaceSummarySerializer

_SYSTEM_ACTOR_CACHE = None


def _get_system_actor():
    global _SYSTEM_ACTOR_CACHE
    if _SYSTEM_ACTOR_CACHE:
        from django.contrib.auth import get_user_model

        exists = get_user_model().objects.filter(pk=_SYSTEM_ACTOR_CACHE.pk).exists()
        if getattr(_SYSTEM_ACTOR_CACHE, "is_active", False) and exists:
            return _SYSTEM_ACTOR_CACHE
        _SYSTEM_ACTOR_CACHE = None
    service = IdentityService()
    actor = service.get_system_actor()
    _SYSTEM_ACTOR_CACHE = actor
    return actor


def _security_metadata(request, extra=None):
    metadata = {
        "ip": extract_client_ip(request),
        "user_agent": request.META.get("HTTP_USER_AGENT"),
    }
    metadata = {k: v for k, v in metadata.items() if v}
    if extra:
        metadata.update(extra)
    return metadata


def _notify_security_event(user, verb: str, event_code: str, request, *, actor=None):
    """Dispatch a security-event notification through the Identity service.

    Tries the Celery task first (fire-and-forget); falls back to the
    synchronous adapter when the broker is unavailable.
    """
    if not user:
        return
    actor = actor or _get_system_actor() or user
    if not actor:
        return
    metadata = _security_metadata(request, {"event": event_code})
    payload = {
        "actor_id": str(actor.id),
        "user_id": str(user.id),
        "verb": verb,
        "event_code": event_code,
        "metadata": metadata,
    }
    if getattr(settings, "SECURITY_EVENTS_ASYNC", True):
        try:
            from components.identity.application.providers.user_task_provider import (
                get_user_task_provider,
            )

            notify_security_event = get_user_task_provider().notify_security_event()
            notify_security_event.delay(**payload)
            return
        except Exception:
            pass
    # Sync fallback — route through the Identity service
    service = IdentityService()
    service.notify_security_event(**payload)


def _build_org_onboarding_payload(user, *, include_workspace_ids=True):
    """Return membership gate data used by the frontend to enforce org onboarding.

    Delegates to BuildOrgOnboardingPayloadQuery via IdentityService.
    """
    user_id = getattr(user, "id", None) if user else None
    service = IdentityService()
    dto = service.build_org_onboarding_payload(user_id=user_id, include_workspace_ids=include_workspace_ids)
    return {
        "requires_org_onboarding": dto.requires_org_onboarding,
        "org_membership_count": dto.org_membership_count,
        "org_access_workspaces": dto.org_access_workspaces,
    }


def _resolve_login_response_mode(request):
    """Return the active login response mode for this request."""
    mode = request.query_params.get("response") or getattr(settings, "LOGIN_RESPONSE_MODE", "legacy")
    mode = (mode or "legacy").lower()
    return "minimal" if mode == "minimal" else "legacy"


def _prefetch_workspace_budgets(workspaces_queryset):
    """No-op after the budgeting context was removed from this fork.

    The nonprofit budgeting domain no longer exists, so there are no budgets to
    prefetch onto workspaces. Returns the queryset unchanged so callers stay
    working.
    """
    return workspaces_queryset


# Cap for the inline projection — full list available via
# GET /me/shared-resources/ when the FE expands the sidebar bucket.
_SHARED_RESOURCES_PROJECTION_CAP = 20


def _build_shared_resources_with_me(user) -> list[dict]:
    """No-op after the resource-sharing context was removed from this fork.

    The sharing domain no longer exists, so there are no shared resources to
    project. Returns ``[]`` so the field's contract is preserved and the
    frontend renders nothing.
    """
    return []


def _build_user_summary_payload(user, request):
    """Return lightweight user, team, and workspace payloads for UI bootstrapping.

    CONSTRAINTS:
     - Uses summary serializers only (no nested members or budgets).
     - Intended for post-login hydration, not full detail views.

    Workspace context is now delegated to BuildUserContextQuery via IdentityService.
    Serialization of ORM objects still requires the ORM querysets for DRF serializers.
    """
    from dataclasses import asdict

    # 1. Build workspace context through the application query (no inline ORM)
    service = IdentityService()
    user_summary = service.build_user_context(user_id=user.id)
    workspace_context = asdict(user_summary.workspace_context)

    # Snapshot the AI chat quota for the active workspace so the chat
    # header can render the messages-remaining pill without a follow-up
    # request. Cross-context call into the agents application layer —
    # adapter is instantiated here at the controller boundary to keep
    # the identity application layer free of agents-context imports.
    # Failure-safe: any error leaves the field as ``None`` and the
    # me/summary endpoint still succeeds.
    if user_summary.workspace_context.active_workspace_id:
        try:
            from components.agents.application.providers.ai_provider import AIProvider
            from components.agents.application.providers.workspace_ai_config_provider import (
                get_workspace_ai_config_provider,
            )
            from components.agents.application.queries.workspace_ai_quota_query import (
                build_workspace_ai_quota_snapshot,
            )

            workspace_context["active_workspace_ai_quota"] = build_workspace_ai_quota_snapshot(
                user_summary.workspace_context.active_workspace_id,
                ai_config_port=get_workspace_ai_config_provider().get_port(),
                ai_run_quota_port=AIProvider.build_ai_run_quota(),
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to build AI quota snapshot for me/summary user=%s",
                user.id,
            )
            workspace_context["active_workspace_ai_quota"] = None

    # Per-workspace branding (WorkspaceTheme brand kit + BrandResolutionService)
    # was NOT ported into this fork — there is no theme model, repository,
    # provider, or write endpoint here, so no workspace can ever carry a brand.
    # ``theme`` stays on the contract as an explicit ``None``: the frontend
    # (``applyWorkspaceTheme`` / ``useActiveWorkspaceBrand`` /
    # ``useWorkspaceAIProfile``) documents ``null`` as "fall back to the
    # Octopus default palette / logo / empty voice tone".
    workspace_context["theme"] = None

    # 2. Serialize ORM objects for DRF response (these stay in the controller
    #    because they require request context for hyperlinked serializers)
    teams = user.teams.filter(status="active").select_related("workspace", "plan").order_by("-id")
    all_workspaces = list(user.get_related_workspaces_queryset().select_related("workspace_owner", "plan"))

    # Personal workspaces are gated per-user by feature.personal_space
    # (globally off in prod, USER-scoped enable for opted-in users — same
    # shape as feature.support_impersonation). When the flag is off we drop
    # the user's own personal workspace from the entire summary; it is not
    # surfaced as a teamspace either, so the gate is authoritative even for
    # personal workspaces minted before the flag existed. The Feed inside
    # the space stays gated separately by feature.social_feed.
    from components.shared_platform.application.facades.feature_flags_facade import (
        is_feature_enabled,
    )

    personal_space_enabled = is_feature_enabled("feature.personal_space", user=user, request=request)
    if not personal_space_enabled:
        all_workspaces = [
            w for w in all_workspaces if not (w.workspace_type == "personal" and w.workspace_owner_id == user.id)
        ]

    # Classify workspaces and resolve persona roles
    from components.identity.domain.policies.workspace_role_policy import resolve_workspace_role

    # Evaluate the teams queryset once. We keep ``user_team_workspace_ids``
    # because the (unrelated) "is this an owned teamspace vs supporting
    # workspace?" classification below still cares whether the user is on
    # any team. Role visibility itself no longer depends on team
    # membership — see ADR 0002 and the persona-driven policy.
    _teams_list = list(teams)
    user_team_workspace_ids = {t.workspace_id for t in _teams_list}

    private_workspace = None
    owned_teamspaces = []
    supporting_workspaces = []
    # Workspaces where the user is a non-owner member on someone else's
    # personal workspace (Adviser / family member / accountant case).
    # Renders under the frontend's "Shared with me" sidebar bucket — see
    # the 2026-06-13 sidebar-pattern research synthesis. The discriminator
    # is workspace_type='personal' AND not is_owner AND has membership row;
    # otherwise these silently landed in supporting_workspaces and looked
    # like donor follows.
    shared_with_me = []
    workspace_roles = {}

    # Bulk-load WorkspaceMembership rows for the user across the
    # workspaces we're about to serialise. Both persona (experience
    # routing — which dashboard / sidebar) and role (RBAC tier — what
    # they can do) live here. The role-policy reads both: admin-tier
    # roles get full sidebar regardless of persona drift, otherwise
    # persona drives the visibility tier. See ADR 0002.
    from components.workspace.application.providers.workspaces_models_provider import (
        get_workspaces_models_provider,
    )

    _pkg_models = get_workspaces_models_provider()
    WorkspaceMembership = _pkg_models.WorkspaceMembership
    # Include PENDING alongside ACTIVE so a self-service volunteer/contributor
    # who is awaiting owner approval still surfaces with their team persona
    # (and lands on the contributor dashboard behind the "pending approval"
    # lock). ``membership_status_by_workspace`` carries the status so the
    # frontend can render that lock — see ``is_pending_approval`` below.
    _membership_rows = list(
        WorkspaceMembership.objects.filter(
            user_id=user.id,
            workspace_id__in=[w.id for w in all_workspaces],
            status__in=(
                WorkspaceMembership.Status.ACTIVE,
                WorkspaceMembership.Status.PENDING,
            ),
            is_impersonation=False,
        ).values_list("workspace_id", "persona", "role", "status")
    )
    membership_by_workspace = {ws_id: (persona, role) for ws_id, persona, role, _status in _membership_rows}
    membership_status_by_workspace = {ws_id: status for ws_id, _persona, _role, status in _membership_rows}
    persona_by_workspace = {ws_id: persona for ws_id, (persona, _role) in membership_by_workspace.items()}

    # Bulk-load the per-workspace AI agent team id so the frontend can
    # deep-link to the agent team's Kanban board (the home for AI
    # findings) without needing a separate round-trip per workspace.
    # See docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md (Phase 1).
    from components.team.application.providers.team_models_provider import (
        get_team_models_provider,
    )

    _pkg_models = get_team_models_provider()
    Team = _pkg_models.Team
    agent_team_id_by_workspace = {
        ws_id: team_id
        for ws_id, team_id in Team.objects.filter(
            workspace_id__in=[w.id for w in all_workspaces],
            kind=Team.Kind.AI_AGENTS,
            status=Team.ACTIVE,
        ).values_list("workspace_id", "id")
    }

    # The donation/transaction ledger (budgeting + sponsorship contexts) was
    # removed from this fork, so there is no donor signal to surface. Keep an
    # empty set so the ``is_donor`` field's contract below is preserved.
    donation_workspace_ids: set = set()

    for w in all_workspaces:
        is_owner = w.workspace_owner_id == user.id
        is_team_member = w.id in user_team_workspace_ids
        is_personal = w.workspace_type == "personal" and is_owner
        # Non-owner with an active membership row on a personal workspace
        # — Adviser / accountant / family member helping with someone
        # else's books. Catches them before they fall through to
        # supporting_workspaces (which mixes donors + followers).
        is_personal_guest = w.workspace_type == "personal" and not is_owner and w.id in membership_by_workspace

        persona, rbac_role = membership_by_workspace.get(w.id, (None, None))
        role = resolve_workspace_role(
            is_owner=is_owner,
            is_personal_workspace=is_personal,
            membership_role=rbac_role,
            membership_persona=persona,
        )
        workspace_roles[str(w.id)] = role

        if is_personal:
            private_workspace = w
        elif is_personal_guest:
            shared_with_me.append(w)
        elif is_owner or is_team_member:
            owned_teamspaces.append(w)
        else:
            supporting_workspaces.append(w)

    def _serialize_workspace(w):
        data = dict(WorkspaceSummarySerializer(w, context=serializer_ctx).data)
        role = workspace_roles.get(str(w.id))
        if role:
            data["role"] = role.role
            data["visible_sections"] = role.visible_sections
        # workspace_type + is_owner is the unambiguous (workspace, viewer)
        # pair the frontend uses to discriminate the three sidebar buckets:
        #   - workspace_type='personal' AND is_owner=True  → Private (yours)
        #   - workspace_type='personal' AND is_owner=False → Shared with me
        #   - workspace_type='teamspace' (any owner)       → Teamspaces
        # Emitting both explicitly (rather than letting the frontend infer
        # from relationship + persona) removes the classification drift
        # between Sidebar.jsx / SeedInfo.jsx / useActiveWorkspace.ts that
        # produced the "Private toggle missing" bug.
        data["workspace_type"] = w.workspace_type
        data["is_owner"] = w.workspace_owner_id == user.id
        # The currency this workspace operates in. The frontend
        # ``useWorkspaceCurrency`` hook reads this off each summary
        # workspace entry to render money in the workspace's own currency
        # (e.g. CA$) instead of a hardcoded USD "$". Falls back to USD so
        # the formatter always has a valid code.
        data["default_currency"] = getattr(w, "default_currency", None) or "USD"
        # Persona is the experience-routing key — frontend dashboard
        # dispatch reads this. Falls back to a sensible default for users
        # who haven't been backfilled yet (legacy heuristic mode).
        persona = persona_by_workspace.get(w.id)
        if not persona:
            if w.workspace_owner_id == user.id and w.workspace_type == "personal":
                persona = "private"
            elif w.workspace_owner_id == user.id:
                persona = "admin"
            else:
                persona = "contributor"
        data["persona"] = persona

        # Membership status — ACTIVE for normal members; PENDING for a
        # self-service volunteer/contributor still awaiting owner approval.
        # The frontend renders a full-surface "pending approval" lock over the
        # persona dashboard while ``is_pending_approval`` is true, then drops it
        # once the owner approves (status flips to ACTIVE).
        membership_status = membership_status_by_workspace.get(w.id)
        data["membership_status"] = membership_status or "active"
        data["is_pending_approval"] = membership_status == "pending"

        # Relationship — distinguishes invited members from followers.
        #
        # ``user.get_related_workspaces_queryset()`` unions four sources:
        # owner, team membership, ``WorkspaceMembership``, and the
        # ``followers`` M2M. The first three are real memberships and
        # earn the workspace dashboard. Follower-only access is a
        # spectator relationship — the user followed the workspace
        # without being invited — and the frontend uses this field to
        # route them to the workspace profile page instead of an empty
        # contributor sidebar (codenry hit that on 2026-05-08 after
        # following CBH's workspace).
        #
        # Computed from already-bulk-loaded data; no new queries.
        is_member = (
            w.workspace_owner_id == user.id or w.id in user_team_workspace_ids or w.id in membership_by_workspace
        )
        data["relationship"] = "member" if is_member else "follower"

        # is_donor — true iff the user has any donation transaction
        # logged against this workspace. Independent of relationship
        # so a member who has also donated is correctly flagged on
        # both axes; the frontend's sidebar puts a member|donor under
        # "Supporting" and a donor-only entry (no membership) under
        # "Supporting" as well rather than "Following".
        data["is_donor"] = w.id in donation_workspace_ids

        # Phase 1 of the Agents-as-Teammates migration — every workspace
        # has an eager-bootstrapped AI agent team. ``None`` is acceptable
        # during the data-migration window and tells the frontend to
        # hide the "Review findings" deep-link.
        data["agent_team_id"] = str(agent_team_id_by_workspace[w.id]) if w.id in agent_team_id_by_workspace else None
        return data

    # 3. Feature flags
    from components.shared_platform.application.facades.feature_flags_facade import flags_for_context

    feature_flags = flags_for_context(
        user=user,
        workspace_id=user_summary.active_workspace_id,
        request=request,
    )

    # 4. Active support impersonation session (if any) — drives the
    # persistent banner + frontend-side workspace switcher entry. The
    # frontend reads ``can_support_impersonate`` to decide whether to
    # render the "Impersonate workspace" entry; ``active_session``
    # populates the banner with countdown + Exit button.
    can_support_impersonate = bool(feature_flags.get("feature.support_impersonation"))
    active_impersonation = None
    if can_support_impersonate:
        from django.utils import timezone

        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        SupportImpersonationSession = _pkg_models.SupportImpersonationSession
        now = timezone.now()
        session = (
            SupportImpersonationSession.objects.filter(
                actor_id=user.id,
                ended_at__isnull=True,
                expires_at__gt=now,
            )
            .select_related("target_workspace")
            .order_by("-started_at")
            .first()
        )
        if session is not None:
            # Derive the visible sections for the impersonated persona/role so
            # the FE can trim the sidebar to what the target would actually
            # see. Without this the FE has no section list and falls back to
            # the full admin sidebar — an untrustworthy preview.
            from components.identity.domain.policies.workspace_role_policy import (
                resolve_workspace_role,
            )

            target_role_obj = resolve_workspace_role(
                is_owner=False,
                is_personal_workspace=False,
                membership_role=session.target_role,
                membership_persona=session.target_persona,
            )
            active_impersonation = {
                "id": str(session.id),
                "target_workspace_id": str(session.target_workspace_id),
                "target_workspace_name": (getattr(session.target_workspace, "workspace_name", "") or ""),
                "target_persona": session.target_persona,
                "target_role": session.target_role,
                "visible_sections": list(target_role_obj.visible_sections),
                "started_at": session.started_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
            }

    serializer_ctx = {"request": request}
    return {
        "user": UserSummarySerializer(user, context=serializer_ctx).data,
        "teams": TeamSummarySerializer(_teams_list, many=True, context=serializer_ctx).data,
        "workspaces": [_serialize_workspace(w) for w in all_workspaces],
        "private_workspace": _serialize_workspace(private_workspace) if private_workspace else None,
        "teamspaces": [_serialize_workspace(w) for w in owned_teamspaces],
        "supporting": [_serialize_workspace(w) for w in supporting_workspaces],
        # Personal workspaces where the user has a non-owner membership —
        # the "Shared with me" bucket. Mirrors Google Drive's universal
        # vocabulary; renders as a third sidebar section below Private
        # and Teamspaces on the frontend. Empty for users who haven't
        # been invited to anyone's personal workspace (the common case).
        "shared_with_me": [_serialize_workspace(w) for w in shared_with_me],
        # Per-RESOURCE shares (budget / task / project / report /
        # newsletter / blog) granted directly to this user. Sibling of
        # ``shared_with_me`` (which is workspace-grain); the two coexist
        # in the same sidebar section but answer different questions —
        # "what whole workspaces was I invited to" vs. "what individual
        # items did someone share with me". Sprint 1 wires the projection
        # field through a NullResourceResolver (always empty); Sprint 2
        # swaps in a composite resolver as entity controllers come online.
        # Behind the ``feature.resource_sharing`` flag — empty list when
        # the flag is off.
        "shared_resources_with_me": _build_shared_resources_with_me(user),
        "workspace_context": workspace_context,
        "feature_flags": feature_flags,
        "can_support_impersonate": can_support_impersonate,
        "active_impersonation": active_impersonation,
    }


from rest_framework.permissions import IsAuthenticated

from components.shared_platform.application.providers.core_utils_provider import (
    get_core_utils_provider,
)
from components.team.mappers.rest.team_serializers import InvitationSerializer, TeamSerializer, TeamSummarySerializer

resolve_frontend_base_url = get_core_utils_provider().resolve_frontend_base_url


class CustomRedirect(HttpResponsePermanentRedirect):
    allowed_schemes = ["https", "http"]


def _build_frontend_url(request, path, site_domain=""):
    normalized_path = path if path.startswith("/") else f"/{path}"
    base = resolve_frontend_base_url(site_domain=site_domain, request=request)
    return f"{base}{normalized_path}"


"""
OTP endpoints are defined in apps.users.otp.views and re-exported via urls.
"""


# ── Users ──


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class RegisterView(generics.GenericAPIView):
    """Register a new user and send verification email.

    User creation is handled by the RegisterSerializer (DRF validation +
    Django model creation). Post-creation email verification is delegated
    to the RegisterUserUseCase via IdentityProvider — keeping business
    orchestration out of the controller.
    """

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = RegisterSerializer
    renderer_classes = (UserRenderer,)

    def post(self, request):
        # 1. Validate and create user via serializer with service in context
        service = IdentityService()
        serializer = self.serializer_class(data=request.data, context={"service": service})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user_data = serializer.data

        new_user = service.find_user_by_email_and_username(user_data["email"], user_data["username"])
        uuid_serializer = UserSerializerUUID(instance=new_user, many=True, context={"request": request})
        response = {
            "data": {
                "uuid": uuid_serializer.data,
                "email": user_data["email"],
                "username": user_data["username"],
            }
        }

        # 2. Resolve site context for email verification URL
        #    Use FRONTEND_URL / LOCALHOST_FRONTEND_URL for email links — NOT the
        #    API's Site domain, which would point users to the backend.
        current_site = get_current_site(request)
        site_domain = getattr(current_site, "domain", current_site)
        site_domain = site_domain.strip() if isinstance(site_domain, str) else ""
        frontend_base = getattr(settings, "FRONTEND_URL", None) or getattr(settings, "LOCALHOST_FRONTEND_URL", "")
        confirm_path = getattr(settings, "EMAIL_CONFIRMATION_REDIRECT_PATH", "/EmailConfirmed/")
        confirmation_base_url = (
            f"{frontend_base.rstrip('/')}{confirm_path}"
            if frontend_base
            else _build_frontend_url(request, confirm_path, site_domain=site_domain)
        )

        # 3. Delegate verification email to the email port via service
        #    (user creation already done by serializer, so we use the adapter
        #    for the email dispatch only)
        user = service.get_user_by_email(user_data["email"])
        token = RefreshToken.for_user(user).access_token
        verification_url = f"{confirmation_base_url}?token={token!s}"

        service = IdentityService()
        email_sent = service.send_verification_email(
            user_id=user.id,
            email=user.email,
            username=user.username,
            verification_url=verification_url,
            site_name=getattr(settings, "SITE_NAME", "Octopus"),
            site_domain=site_domain,
        )
        if not email_sent:
            response["warning"] = "Account created, but verification email could not be sent right now."

        return Response(response, status=status.HTTP_200_OK)


class VerifyEmail(views.APIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    throttle_classes = [EmailVerifyThrottle]
    serializer_class = EmailVerificationSerializer

    token_param_config = OpenApiParameter(
        name="token",
        location=OpenApiParameter.QUERY,
        description="Description",
        type=str,
    )

    @extend_schema(parameters=[token_param_config])
    def get(self, request):
        """Verify email via token — delegated to VerifyEmailUseCase."""
        from components.identity.application.commands.verify_email_command import (
            VerifyEmailCommand,
            VerifyEmailFailure,
        )

        token = request.GET.get("token")
        if not token:
            return Response({"error": "Token parameter missing"}, status=status.HTTP_400_BAD_REQUEST)

        context = build_request_context(request)
        service = IdentityService()
        result = service.verify_email(VerifyEmailCommand(token=token, context=context))

        if isinstance(result, VerifyEmailFailure):
            return Response({"error": result.message}, status=status.HTTP_400_BAD_REQUEST)

        auth_payload = {
            "pk": str(result.user_id),
            "email": result.email,
            "username": result.username,
            "is_onboard_complete": result.is_onboard_complete,
            "is_contributor": result.is_contributor,
            "tokens": result.tokens,
        }
        return Response({**auth_payload, "detail": "Successfully activated"}, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        """
        Load one-to-one profile data up front to avoid N+1s when serializing
        nested user payloads.
        """
        service = IdentityService()
        return service.get_user_queryset()

    # User permissions
    def get_permissions(self):
        permission_classes = []
        if self.action == "create":
            permission_classes = [AllowAny]
        elif self.action == "retrieve" or self.action == "update" or self.action == "partial_update":
            permission_classes = [IsLoggedInUserOrAdmin]

        elif self.action == "list" or self.action == "destroy":
            permission_classes = [
                IsUnauthenticatedOrAdminOrStaff,
            ]
        return [permission() for permission in permission_classes]


class UserInvitationDetails(APIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "user-invitation-detail"
    serializer_class = InvitationSerializer

    def post(self, request, *args, **kwargs):
        user_id = request.data.get("user")
        email = request.data.get("email")

        if not user_id or not email:
            return Response(
                {"detail": 'Both "user" and "email" fields are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = IdentityService()
        userprofile = service.get_user_profile(user_id)

        if userprofile is None:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        invitations = service.list_pending_invitations(email)
        invitations_serializer = InvitationSerializer(invitations, many=True, context={"request": request})

        return Response(
            {
                "success": "true",
                "status code": status.HTTP_200_OK,
                "message": "Found!",
                "data": {
                    "invitations": invitations_serializer.data,
                },
            },
            status=status.HTTP_200_OK,
        )


class UserDetails(APIView):
    """Return user details; supports ?mode=summary for a lightweight payload."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    name = "legacy-user-detail"
    serializer_class = UserSerializer

    def get(self, request, id=None, format=None):
        target_id = id or request.user.id
        service = IdentityService()
        user = service.get_user_by_id(target_id, with_profile=True)
        if not user:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response_mode = request.query_params.get("mode")
        if response_mode and response_mode.lower() == "summary":
            data = _build_user_summary_payload(user, request)
            return Response({"data": data}, status=status.HTTP_200_OK)

        teams = (
            user.teams.filter(status="active")
            .select_related("workspace", "plan")
            .prefetch_related("members__profile")
            .order_by("-id")
        )
        all_workspaces = user.get_related_workspaces_queryset().select_related("workspace_owner", "plan")
        all_workspaces = _prefetch_workspace_budgets(all_workspaces)

        team_serializer = TeamSerializer(teams, many=True, context={"request": request})
        user_serializer = UserSerializer(user, context={"request": request, "service": service})
        WorkspaceSerializer = _workspace_serializer()
        workspace_serializer = WorkspaceSerializer(all_workspaces, many=True, context={"request": request})

        data = {"user": user_serializer.data, "teams": team_serializer.data, "workspaces": workspace_serializer.data}
        return Response({"data": data}, status=status.HTTP_200_OK)


class UserSummaryView(APIView):
    """Return lightweight user, team, and workspace data for post-login hydration."""

    permission_classes = (IsAuthenticated,)
    name = "user-summary"
    serializer_class = UserSummarySerializer

    def get(self, request, format=None):
        service = IdentityService()
        user = service.get_user_by_id(request.user.id, with_profile=True)
        if user is None:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Idempotent workspace bootstrap — ensure workspace exists for onboarded users
        from components.identity.application.providers.workspace_bootstrap_provider import (
            get_workspace_bootstrap_provider,
        )

        should_bootstrap_workspace = get_workspace_bootstrap_provider().should_bootstrap_workspace
        if should_bootstrap_workspace(user):
            ensure_user_workspace_context(user, create_if_missing=True)
        data = _build_user_summary_payload(user, request)
        return Response({"data": data}, status=status.HTTP_200_OK)


# Personas + roles permitted on a SupportImpersonationSession. Mirrors
# the WorkspaceMembership.Persona / Role enum but excludes sentinel
# values that don't make sense for impersonation (e.g. "private").
_IMPERSONATION_PERSONAS = frozenset({"admin", "contributor", "volunteer", "sponsor", "auditor", "board_member"})
_IMPERSONATION_ROLES = frozenset({"owner", "admin", "member", "viewer"})
_IMPERSONATION_TTL_MINUTES = 30


def _serialize_session(session) -> dict:
    return {
        "id": str(session.id),
        "target_workspace_id": str(session.target_workspace_id),
        "target_workspace_name": (getattr(session.target_workspace, "workspace_name", "") or ""),
        "target_persona": session.target_persona,
        "target_role": session.target_role,
        "reason": session.reason or "",
        "started_at": session.started_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "ended_at": (session.ended_at.isoformat() if session.ended_at else None),
    }


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class SupportImpersonationSessionView(APIView):
    """POST /identity/me/impersonation-sessions/  — start a session.
    GET  /identity/me/impersonation-sessions/  — list active sessions.

    Start body:
        {
          "workspace_id": "<uuid>",
          "persona": "<one-of-six>",
          "role": "<owner|admin|member|viewer>",
          "password": "<re-auth>",
          "reason": "<free text, optional>"
        }

    Returns the session payload on success. Creates a synthetic
    ``WorkspaceMembership`` row (``is_impersonation=True``) so existing
    permission checks see the actor as having the chosen role/persona
    on the target workspace for 30 minutes. Active session is also
    surfaced on ``me/summary`` as ``support_impersonation``.

    Gating: requires ``feature.support_impersonation`` per-user. Reason
    field is intentionally optional in MVP but recorded when supplied.
    """

    permission_classes = (IsAuthenticated,)
    name = "support-impersonation-sessions"

    def get(self, request, *args, **kwargs):
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        SupportImpersonationSession = _pkg_models.SupportImpersonationSession

        now = timezone.now()
        sessions = (
            SupportImpersonationSession.objects.filter(
                actor_id=request.user.id,
                ended_at__isnull=True,
                expires_at__gt=now,
            )
            .select_related("target_workspace")
            .order_by("-started_at")
        )
        return Response(
            {"results": [_serialize_session(s) for s in sessions]},
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):

        from django.contrib.auth import authenticate

        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        db_transaction = _django_orm.transaction
        from django.utils import timezone

        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        is_feature_enabled = get_feature_flags_provider().is_feature_enabled
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        SupportImpersonationSession = _pkg_models.SupportImpersonationSession
        Workspace = _pkg_models.Workspace
        WorkspaceMembership = _pkg_models.WorkspaceMembership
        WorkspaceRole = _pkg_models.WorkspaceRole

        actor = request.user
        if not is_feature_enabled("feature.support_impersonation", user=actor, request=request):
            return Response(
                {"error": "Support impersonation is not enabled for your account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_id = (request.data.get("workspace_id") or "").strip()
        persona = (request.data.get("persona") or "").strip().lower()
        role = (request.data.get("role") or "").strip().lower()
        password = request.data.get("password") or ""
        reason = (request.data.get("reason") or "").strip()

        if persona not in _IMPERSONATION_PERSONAS:
            return Response(
                {"error": (f"persona must be one of {sorted(_IMPERSONATION_PERSONAS)}.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if role not in _IMPERSONATION_ROLES:
            return Response(
                {"error": (f"role must be one of {sorted(_IMPERSONATION_ROLES)}.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not workspace_id:
            return Response(
                {"error": "workspace_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is None:
            return Response(
                {"error": "Workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Re-auth is required only when starting a session escalates
        # privilege — i.e. the actor isn't already an OWNER/ADMIN on
        # the target workspace via a real (non-impersonation)
        # membership. Previewing your own org as contributor is a
        # frequent dev workflow and shouldn't ask for a password
        # every 30 minutes; troubleshooting a customer's workspace
        # IS escalation and SHOULD ask.
        is_already_admin = (
            str(workspace.workspace_owner_id) == str(actor.id)
            or WorkspaceMembership.objects.filter(
                workspace=workspace,
                user=actor,
                status=WorkspaceMembership.Status.ACTIVE,
                is_impersonation=False,
                role__in=[
                    WorkspaceMembership.Role.OWNER,
                    WorkspaceMembership.Role.ADMIN,
                ],
            ).exists()
        )
        if not is_already_admin:
            if not password:
                return Response(
                    {"error": ("Re-enter your password to impersonate on a workspace you don't already administer.")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            verified = authenticate(
                request,
                username=getattr(actor, "email", actor.username),
                password=password,
            )
            if verified is None or verified.id != actor.id:
                return Response(
                    {"error": "Password is incorrect."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # End any prior active session the actor has — only one impersonation
        # session at a time (per actor). The Celery cleanup task also catches
        # expired sessions, but explicit close keeps state tight.
        now = timezone.now()
        prior = (
            SupportImpersonationSession.objects.filter(
                actor_id=actor.id,
                ended_at__isnull=True,
                expires_at__gt=now,
            )
            .select_related("synthetic_membership")
            .first()
        )
        if prior is not None:
            with db_transaction.atomic():
                if prior.synthetic_membership_id:
                    WorkspaceMembership.objects.filter(id=prior.synthetic_membership_id).delete()
                prior.synthetic_membership = None
                prior.ended_at = now
                prior.save(update_fields=["synthetic_membership", "ended_at"])

        system_role = WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=role).first()

        with db_transaction.atomic():
            membership = WorkspaceMembership.objects.create(
                workspace=workspace,
                user=actor,
                role=role,
                workspace_role=system_role,
                persona=persona,
                status=WorkspaceMembership.Status.ACTIVE,
                is_impersonation=True,
                accepted_at=now,
            )
            session = SupportImpersonationSession.objects.create(
                actor=actor,
                target_workspace=workspace,
                target_persona=persona,
                target_role=role,
                reason=reason,
                expires_at=now + timedelta(minutes=_IMPERSONATION_TTL_MINUTES),
                synthetic_membership=membership,
            )

        return Response(
            _serialize_session(session),
            status=status.HTTP_201_CREATED,
        )


class SupportImpersonationSessionEndView(APIView):
    """DELETE /identity/me/impersonation-sessions/<uuid:session_id>/

    End a session early. Idempotent — ending an already-ended session
    returns 200 with the existing payload. Gated so callers can only
    end their own sessions.
    """

    permission_classes = (IsAuthenticated,)
    name = "support-impersonation-session-end"

    def delete(self, request, session_id=None, *args, **kwargs):
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        db_transaction = _django_orm.transaction
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        SupportImpersonationSession = _pkg_models.SupportImpersonationSession
        WorkspaceMembership = _pkg_models.WorkspaceMembership

        session = (
            SupportImpersonationSession.objects.filter(id=session_id, actor_id=request.user.id)
            .select_related("target_workspace")
            .first()
        )
        if session is None:
            return Response(
                {"error": "Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if session.ended_at is None:
            with db_transaction.atomic():
                if session.synthetic_membership_id:
                    WorkspaceMembership.objects.filter(id=session.synthetic_membership_id).delete()
                session.synthetic_membership = None
                session.ended_at = timezone.now()
                session.save(update_fields=["synthetic_membership", "ended_at"])

        return Response(_serialize_session(session), status=status.HTTP_200_OK)


class UserList(generics.ListAPIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserSerializer
    name = "customuser-list"

    def get_queryset(self):
        service = IdentityService()
        return service.get_user_queryset()


# class UserDetail(generics.RetrieveAPIView):
#     permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
#     queryset = CustomUser.objects.all()
#     serializer_class = UserSerializer
#     name = 'customuser-detail'


class ProfileEditView(APIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserProfileSerializer

    def patch(self, request, uuid=None):
        service = IdentityService()
        profile = service.get_user_profile(uuid)
        if profile is None:
            return Response(
                {"status": "error", "data": {"detail": "User profile not found."}}, status=status.HTTP_404_NOT_FOUND
            )
        serializer = UserProfileSerializer(
            profile, data=request.data, partial=True, context={"request": request, "service": service}
        )
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data})
        else:
            return Response({"status": "error", "data": serializer.errors})


class UserPatchView(APIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserPatchSerializer

    def patch(self, request, uuid=None):
        service = IdentityService()
        preference = service.get_user_by_id(uuid)
        if preference is None:
            return Response(
                {"status": "error", "data": {"detail": "User not found."}}, status=status.HTTP_404_NOT_FOUND
            )
        was_onboarded = getattr(preference, "is_onboard_complete", False)
        serializer = UserPatchSerializer(
            preference, data=request.data, partial=True, context={"request": request, "service": service}
        )
        if serializer.is_valid():
            user = serializer.save()
            # Bootstrap workspace when onboarding completes. Any chosen
            # workspace_name is already applied by the serializer's bootstrap
            # (UserPatchSerializer.update runs during serializer.save() above
            # and creates the named workspace); this call is an idempotent
            # safety net that resolves the existing one.
            if not was_onboarded and getattr(user, "is_onboard_complete", False):
                ensure_user_workspace_context(user, create_if_missing=True)
            return Response({"status": "success", "data": serializer.data})
        else:
            return Response({"status": "error", "data": serializer.errors})


class SignupAPI(APIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserSerializer

    @extend_schema(request=UserSerializer)
    def post(self, request):
        data = request.data
        service = IdentityService()
        serializer = UserSerializer(data=data, context={"request": request, "service": service})
        if serializer.is_valid():
            serializer.save()
            return Response({"msg": "Data Created"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class LoginAPIView(generics.GenericAPIView):
    """Authenticate a user and return tokens with onboarding flags.

    Business logic delegated to LoginUseCase via IdentityProvider.
    This controller handles only HTTP concerns: input extraction,
    response mode selection, and response formatting.
    """

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    throttle_classes = [LoginThrottle]
    serializer_class = LoginSerializer

    def post(self, request):
        from rest_framework.exceptions import AuthenticationFailed

        from components.identity.application.commands.login_command import (
            LoginCommand,
            LoginFailure,
        )

        # 1. Extract and validate input shape
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        if not email or not password:
            return Response(
                {"detail": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Delegate to use case
        context = build_request_context(request)
        service = IdentityService()
        result = service.login(LoginCommand(email=email, password=password, context=context))

        # 3. Handle failure
        if isinstance(result, LoginFailure):
            raise AuthenticationFailed(detail=result.message)

        # 4. Build response with onboarding payload
        user = service.get_user_by_id(result.user_id)
        response_mode = _resolve_login_response_mode(request)
        onboarding_payload = _build_org_onboarding_payload(
            user,
            include_workspace_ids=response_mode == "legacy",
        )

        login_data = {
            "pk": str(result.user_id),
            "email": result.email,
            "username": result.username,
            "is_onboard_complete": result.is_onboard_complete,
            "is_contributor": result.is_contributor,
            "two_factor_enabled": result.two_factor_enabled,
            "two_factor_confirmed_at": result.two_factor_confirmed_at,
            "tokens": result.tokens,
            "otp_required": result.otp_required,
            "preauth_token": result.preauth_token,
        }

        if response_mode == "minimal":
            response_data = {
                "tokens": login_data.get("tokens"),
                "otp_required": login_data.get("otp_required"),
                "preauth_token": login_data.get("preauth_token"),
                "user_id": str(result.user_id),
                "email": login_data.get("email"),
                "username": login_data.get("username"),
                "is_onboard_complete": login_data.get("is_onboard_complete"),
                "is_contributor": login_data.get("is_contributor"),
                "requires_org_onboarding": onboarding_payload.get("requires_org_onboarding"),
                "org_membership_count": onboarding_payload.get("org_membership_count"),
            }
        else:
            response_data = dict(login_data)
            response_data.update(onboarding_payload)
        return Response(response_data, status=status.HTTP_200_OK)


class RequestPasswordResetEmail(generics.GenericAPIView):
    """Request a password reset email — delegated to RequestPasswordResetUseCase."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    throttle_classes = [PasswordResetRequestThrottle]
    serializer_class = ResetPasswordEmailRequestSerializer

    def post(self, request):
        from components.identity.application.commands.reset_password_command import (
            RequestPasswordResetCommand,
        )

        email = request.data.get("email", "")
        redirect_url = request.data.get("redirect_url", "")
        current_site = get_current_site(request=request)
        site_domain = getattr(current_site, "domain", current_site)
        site_domain = site_domain.strip() if isinstance(site_domain, str) else ""
        reset_base_url = _build_frontend_url(request, "", site_domain=site_domain)

        context = build_request_context(request)
        service = IdentityService()
        result = service.request_password_reset(
            RequestPasswordResetCommand(
                email=email,
                reset_base_url=reset_base_url,
                redirect_url=redirect_url,
                context=context,
            )
        )

        return Response({"success": result.message}, status=status.HTTP_200_OK)


class PasswordTokenCheckAPI(generics.GenericAPIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    throttle_classes = [PasswordResetConfirmThrottle]
    serializer_class = SetNewPasswordSerializer

    def get(self, request, uidb64, token):
        redirect_url = request.GET.get("redirect_url", "")
        # Settings-driven frontend base (FRONTEND_URL in prod) — never a
        # hardcoded domain — used when the caller supplied no redirect_url.
        fallback_url = _build_frontend_url(request, "")
        try:
            id = smart_str(urlsafe_base64_decode(uidb64))
            service = IdentityService()
            user = service.get_user_by_id(id)
            if user is None:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
            if not PasswordResetTokenGenerator().check_token(user, token):
                if len(redirect_url) > 3:
                    return CustomRedirect(redirect_url + "?token_valid=False")
                else:
                    return CustomRedirect(fallback_url + "?token_valid=False")
            if redirect_url and len(redirect_url) > 3:
                return CustomRedirect(
                    redirect_url + "?token_valid=True&message=Credentials Valid&uidb64=" + uidb64 + "&token=" + token
                )
            else:
                return CustomRedirect(fallback_url + "?token_valid=False")
        except DjangoUnicodeDecodeError:
            try:
                if not PasswordResetTokenGenerator().check_token(user):
                    return CustomRedirect(redirect_url + "?token_valid=False")
            except UnboundLocalError:
                return Response(
                    {"error": "Token is not valid, please request a new one"}, status=status.HTTP_400_BAD_REQUEST
                )


@method_decorator(sensitive_post_parameters("password", "token"), name="dispatch")
class SetNewPasswordAPIView(generics.GenericAPIView):
    """Set a new password after reset — fully delegated to SetNewPasswordUseCase.

    Business logic (token validation, password setting, audit, notification)
    is handled by the use case. This controller handles only HTTP concerns:
    input extraction and response formatting.
    """

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    throttle_classes = [PasswordResetConfirmThrottle]
    serializer_class = SetNewPasswordSerializer

    def patch(self, request):
        from components.identity.application.commands.reset_password_command import (
            SetNewPasswordCommand,
            SetNewPasswordFailure,
        )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        context = build_request_context(request)
        service = IdentityService()
        result = service.set_new_password(
            SetNewPasswordCommand(
                uidb64=serializer.validated_data.get("uidb64", ""),
                token=serializer.validated_data.get("token", ""),
                new_password=serializer.validated_data.get("password", ""),
                context=context,
            )
        )

        if isinstance(result, SetNewPasswordFailure):
            return Response(
                {"error": result.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True, "message": "Password reset success"}, status=status.HTTP_200_OK)


@method_decorator(sensitive_post_parameters("refresh"), name="dispatch")
class LogoutAPIView(generics.GenericAPIView):
    """Logout — idempotent token revocation with best-effort audit.

    Logout is a statement of intent. The endpoint MUST always return 204:
    a missing, expired, malformed, or unrecognized refresh token does not
    block the user from logging out. The server makes a best effort to
    blacklist what it can and records an audit event when a user can be
    identified.

    Authentication is optional — by the time a user clicks "log out" their
    access token may already have expired, and rejecting that request is
    exactly the production failure this endpoint must avoid.
    """

    serializer_class = LogoutSerializer
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        # tolerate completely missing/invalid bodies — never raise
        serializer.is_valid(raise_exception=False)

        # Best-effort: identify the session of the submitted refresh token so
        # single-device logout can revoke exactly that session's registry row.
        # MUST run BEFORE serializer.save() — once the token is blacklisted,
        # RefreshToken(...) refuses to parse it (check_blacklist).
        submitted_refresh_jti = None
        raw_refresh = str(request.data.get("refresh") or "").strip() if hasattr(request.data, "get") else ""
        if raw_refresh:
            try:
                submitted_refresh_jti = str(RefreshToken(raw_refresh)["jti"])
            except Exception:
                # Malformed/expired token — logout still proceeds; session
                # registry cleanup for it is simply skipped.
                submitted_refresh_jti = None

        try:
            serializer.save()
        except Exception:
            logger.exception("logout: refresh-token blacklist failed; continuing")

        logout_all = str(request.data.get("all_devices", "false")).strip().lower() in {"1", "true", "yes", "on"}
        token_revoked = bool(getattr(serializer, "token_revoked", False))

        if getattr(request.user, "is_authenticated", False):
            try:
                from components.identity.application.use_cases.logout_use_case import LogoutCommand

                context = build_request_context(request)
                IdentityService().logout(
                    LogoutCommand(
                        user_id=request.user.id,
                        email=getattr(request.user, "email", ""),
                        all_devices=logout_all,
                        context=context,
                        refresh_jti=submitted_refresh_jti,
                    )
                )
                _notify_security_event(request.user, "logged out", "auth.logout", request)
            except Exception:
                logger.exception(
                    "logout: audit pipeline failed for user_id=%s",
                    getattr(request.user, "id", None),
                )

        response = Response(status=status.HTTP_204_NO_CONTENT)
        # Lets the frontend log a precise outcome without ever blocking on it.
        response["X-Token-Revoked"] = "1" if token_revoked else "0"
        return response


class UserSearch(generics.ListCreateAPIView):
    """Search users by username or email using a query param or path value."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserSerializer

    def get(self, request, *args, **kwargs):
        query = kwargs.get("query") or self.request.GET.get("query")
        service = IdentityService()
        # Use lazy import to filter the queryset
        queryset = service.get_user_queryset()
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        Q = _django_orm.Q
        profile_list = queryset.filter(Q(username__icontains=query) | Q(email__icontains=query))
        serializer = UserSerializer(instance=profile_list, many=True, context={"request": request, "service": service})
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(operation_id="users_search_by_query_list"),
    post=extend_schema(operation_id="users_search_by_query_create"),
)
class UserSearchByQuery(UserSearch):
    """Path-based user search for unique schema operation IDs."""

    name = "user-search-by-query"


@method_decorator(
    sensitive_post_parameters("old_password", "new_password", "confirm_password"),
    name="dispatch",
)
class ChangePasswordView(UpdateAPIView):
    """Change the authenticated user's password.

    Business logic delegated to ChangePasswordUseCase via IdentityProvider.
    This controller handles only HTTP concerns: input extraction and response formatting.
    """

    serializer_class = ChangePasswordSerializer

    def get_queryset(self):
        from components.identity.application.providers.users_models_provider import (
            get_users_models_provider,
        )

        _pkg_models = get_users_models_provider()
        CustomUser = _pkg_models.CustomUser
        return CustomUser.objects.all()

    permission_classes = [IsLoggedInUserOrAdmin]

    def get_object(self, queryset=None):
        return self.request.user

    def update(self, request, *args, **kwargs):
        from components.identity.application.commands.change_password_command import (
            ChangePasswordCommand,
            ChangePasswordFailure,
        )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        context = build_request_context(request)
        service = IdentityService()
        result = service.change_password(
            ChangePasswordCommand(
                user_id=request.user.id,
                email=getattr(request.user, "email", ""),
                old_password=serializer.validated_data["old_password"],
                new_password=serializer.validated_data["new_password"],
                confirm_password=serializer.validated_data["confirm_password"],
                context=context,
            )
        )

        if isinstance(result, ChangePasswordFailure):
            return Response(
                {result.field: result.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": result.message,
            },
            status=status.HTTP_200_OK,
        )


class ListWorkspaces(RetrieveAPIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)

    def get_serializer_class(self):
        return _workspace_serializer()

    def get(self, request, pk, *args, **kwargs):
        try:
            user_id = uuid.UUID(str(pk))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid user id. Must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = IdentityService()
        user = service.get_user_by_id(user_id)
        if user is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        from components.identity.application.providers.workspace_bootstrap_provider import (
            get_workspace_bootstrap_provider,
        )

        should_bootstrap_workspace = get_workspace_bootstrap_provider().should_bootstrap_workspace
        if (
            getattr(request.user, "is_authenticated", False)
            and str(request.user.id) == str(user.id)
            and should_bootstrap_workspace(user)
        ):
            ensure_user_workspace_context(user, create_if_missing=True)

        workspaces = user.get_related_workspaces_queryset()
        WorkspaceSerializer = _workspace_serializer()
        serializer = WorkspaceSerializer(instance=workspaces, many=True, context={"request": request})
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)


def _workspace_serializer():
    from components.workspace.application.facades.serializer_facade import WorkspaceGetSerializer

    return WorkspaceGetSerializer


# ── OTP ──


class TOTPCreateView(views.APIView):
    """Set up a new TOTP device — delegates to SetupOTPUseCase."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request, format=None):
        from components.identity.application.commands.otp_commands import SetupOTPCommand

        service = IdentityService()
        result = service.setup_otp(SetupOTPCommand(user_id=request.user.id))
        return Response({"otpauth_url": result.otpauth_url}, status=status.HTTP_200_OK)


@method_decorator(sensitive_post_parameters("token"), name="dispatch")
class TOTPVerifyView(views.APIView):
    """Verify/enable a TOTP device — delegates to VerifyOTPUseCase."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request, token=None, format=None):
        from components.identity.application.commands.otp_commands import (
            VerifyOTPCommand,
            VerifyOTPFailure,
        )

        submitted_token = request.data.get("token") or token
        if not submitted_token:
            return Response({"detail": "token is required"}, status=status.HTTP_400_BAD_REQUEST)

        context = build_request_context(request)
        service = IdentityService()
        result = service.verify_otp(
            VerifyOTPCommand(
                user_id=request.user.id,
                email=getattr(request.user, "email", ""),
                token=str(submitted_token),
                method="totp",
                context=context,
            )
        )

        if isinstance(result, VerifyOTPFailure):
            if result.locked:
                return Response(
                    {"detail": result.message},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response({"detail": result.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"otp_verified": result.otp_verified, "tokens": result.tokens},
            status=status.HTTP_200_OK,
        )


class StaticCreateView(views.APIView):
    """Create static recovery codes.

    NOTE: This controller still uses the OTP device adapter directly because
    the logic is trivial (password check + token generation). A full use case
    extraction would be over-engineering for this flow.
    """

    permission_classes = [permissions.IsAuthenticated, IsTwoFactorEnabledAndVerified]
    number_of_static_tokens = 6
    serializer_class = PasswordConfirmSerializer

    def post(self, request, format=None):
        from django_otp.plugins.otp_static.models import StaticDevice, StaticToken

        from components.identity.application.providers.user_utils_provider import (
            get_user_utils_provider,
        )

        get_user_static_device = get_user_utils_provider().get_user_static_device

        # Recovery codes are a 2FA backup — they're meaningless (and shouldn't be
        # mintable) for an account that hasn't enabled 2FA. The shared
        # IsTwoFactorEnabledAndVerified permission is "verified IF enabled" (it
        # allows when 2FA is off, by design, for other endpoints), so enforce the
        # "must be enabled" half explicitly here.
        if not getattr(request.user, "two_factor_enabled", False):
            return Response(
                {"detail": "Two-factor authentication must be enabled to generate recovery codes."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["password"]):
            return Response({"detail": "Invalid password"}, status=status.HTTP_400_BAD_REQUEST)

        device = get_user_static_device(request.user)
        if not device:
            device = StaticDevice.objects.create(user=request.user, name="Static")

        device.token_set.all().delete()
        tokens = []
        for _n in range(self.number_of_static_tokens):
            token = StaticToken.random_token()
            device.token_set.create(token=token)
            tokens.append(token)

        return Response({"recovery_codes": tokens}, status=status.HTTP_201_CREATED)


@method_decorator(sensitive_post_parameters("token"), name="dispatch")
class StaticVerifyView(views.APIView):
    """Verify a static recovery code — delegates to VerifyOTPUseCase with method='static'."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer
    throttle_classes = [StaticVerifyThrottle]

    def post(self, request, token=None, format=None):
        from components.identity.application.commands.otp_commands import (
            VerifyOTPCommand,
            VerifyOTPFailure,
        )

        submitted_token = request.data.get("token") or token
        if not submitted_token:
            return Response({"detail": "token is required"}, status=status.HTTP_400_BAD_REQUEST)

        context = build_request_context(request)
        service = IdentityService()
        result = service.verify_otp(
            VerifyOTPCommand(
                user_id=request.user.id,
                email=getattr(request.user, "email", ""),
                token=str(submitted_token),
                method="static",
                context=context,
            )
        )

        if isinstance(result, VerifyOTPFailure):
            if result.locked:
                return Response(
                    {"detail": result.message},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response({"detail": result.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"otp_verified": result.otp_verified, "tokens": result.tokens},
            status=status.HTTP_200_OK,
        )


class TOTPDeleteView(views.APIView):
    """Delete TOTP device and disable 2FA — delegates to DisableOTPUseCase."""

    permission_classes = [permissions.IsAuthenticated, IsTwoFactorEnabledAndVerified]
    serializer_class = PasswordConfirmSerializer

    def post(self, request, format=None):
        from components.identity.application.commands.otp_commands import DisableOTPCommand

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["password"]):
            return Response({"detail": "Invalid password"}, status=status.HTTP_400_BAD_REQUEST)

        service = IdentityService()
        result = service.disable_otp(DisableOTPCommand(user_id=request.user.id))

        return Response(
            {"two_factor_enabled": result.two_factor_enabled, "tokens": result.tokens},
            status=status.HTTP_200_OK,
        )


# ── Social Auth ──


class GoogleSocialAuthView(GenericAPIView):
    """`POST /identity/google/`

    Exchange a Google ID token (the ``credential`` the frontend gets from
    Google Identity Services) for a platform JWT session. Passwordless:
    verifies the token, links by Google ``sub`` / verified email or
    creates a fresh account, and returns the SAME response shape as
    ``LoginAPIView`` so the frontend session plumbing works unchanged.

    Orchestration lives in ``AuthenticateWithGoogleUseCase`` behind ports
    (§8a thin controller). No shared password — the old ``SOCIAL_SECRET``
    path is gone.
    """

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = GoogleSocialAuthSerializer

    def post(self, request):
        from components.identity.application.ports.google_auth_port import (
            GoogleAuthError,
        )
        from components.identity.application.providers.google_auth_provider import (
            get_google_auth_provider,
        )
        from components.identity.application.use_cases.authenticate_with_google_use_case import (
            AuthenticateWithGoogleUseCase,
        )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = serializer.validated_data["auth_token"]

        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        provider = get_google_auth_provider()
        use_case = AuthenticateWithGoogleUseCase(
            verifier=provider.verifier(),
            google_auth=provider.store(),
            session_registry=IdentityProvider.build_session_registry(),
        )
        result = use_case.execute(
            raw_token=raw_token,
            context=build_request_context(request),
        )

        if isinstance(result, GoogleAuthError):
            return Response(
                {"error": result.message, "code": result.code},
                status=result.status,
            )

        # Success — mirror LoginAPIView's post-auth side effects + shape.
        service = IdentityService()
        user = service.get_user_by_id(result.user_id)

        # Idempotent workspace bootstrap so a brand-new social user has a
        # personal-workspace context, exactly like the summary path does.
        try:
            ensure_user_workspace_context(user, create_if_missing=False)
        except Exception:
            logger.exception(
                "google_auth_workspace_bootstrap_failed user_id=%s",
                result.user_id,
            )

        # Audit trail — parity with email login (best-effort, never blocks).
        try:
            _notify_security_event(user, "logged in with Google", "auth.login", request)
        except Exception:
            logger.exception(
                "google_auth_security_event_failed user_id=%s",
                result.user_id,
            )

        response_mode = _resolve_login_response_mode(request)
        onboarding_payload = _build_org_onboarding_payload(user, include_workspace_ids=response_mode == "legacy")

        response_data = {
            "pk": str(result.user_id),
            "user_id": str(result.user_id),
            "email": result.email,
            "username": result.username,
            "is_onboard_complete": result.is_onboard_complete,
            "is_contributor": result.is_contributor,
            "auth_provider": "google",
            "created_user": result.created_user,
            "tokens": {
                "access": result.access_token,
                "refresh": result.refresh_token,
            },
            "otp_required": False,
            "preauth_token": None,
        }
        if response_mode == "minimal":
            response_data["requires_org_onboarding"] = onboarding_payload.get("requires_org_onboarding")
            response_data["org_membership_count"] = onboarding_payload.get("org_membership_count")
        else:
            response_data.update(onboarding_payload)
        return Response(response_data, status=status.HTTP_200_OK)


# ── Passwordless magic-link sign-in ──────────────────────────────────


class MagicLinkRequestView(views.APIView):
    """`POST /identity/magic-link/request/`

    Mints a single-use sign-in token and emails it to the donor.
    Closes the loop on the public donate flow's "track this gift" CTA:
    a donor who gave with email X requests a magic link, clicks it,
    lands on /donations/mine with past gifts already attributed by
    email match.

    Anti-enumeration: the response is identical (200 with a generic
    message) regardless of whether the email matches an existing
    account. The throttle prevents flood-scanning the email column.
    """

    name = "magic-link-request"
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = []

    def get_throttles(self):
        from components.identity.api.throttles import (
            MagicLinkRequestThrottle,
        )

        return [MagicLinkRequestThrottle()]

    def post(self, request):
        from components.identity.application.providers.magic_link_provider import (
            get_magic_link_provider,
        )
        from components.identity.application.use_cases.request_magic_link_use_case import (
            DEFAULT_TTL_MINUTES,
            RequestMagicLinkUseCase,
        )

        _magic_link = get_magic_link_provider()
        DjangoMagicLinkEmailAdapter = _magic_link.email_sender
        OrmMagicLinkAdapter = _magic_link.store

        email = (request.data.get("email") or "").strip()
        next_url = request.data.get("next") or request.data.get("next_url") or ""
        generic_ok = Response(
            {
                "status": "ok",
                "message": ("If that email is associated with an account, a sign-in link is on its way."),
            },
            status=status.HTTP_200_OK,
        )
        if not email:
            return generic_ok

        try:
            result = RequestMagicLinkUseCase(magic_link=OrmMagicLinkAdapter()).execute(email=email, next_url=next_url)
        except Exception:
            logger.exception("magic_link_request_failed email=%s", email)
            return generic_ok
        if result is None:
            return generic_ok

        try:
            current_site = get_current_site(request)
            site_domain = getattr(current_site, "domain", "") or ""
            site_name = getattr(settings, "SITE_NAME", "Octopus")
            frontend_base = (
                getattr(settings, "FRONTEND_URL", None)
                or getattr(settings, "LOCALHOST_FRONTEND_URL", "")
                or f"https://{site_domain}"
            )
            verify_path = f"/identity/magic-link/verify?token={result.token}"
            if result.next_url:
                from urllib.parse import quote as _quote

                verify_path = f"{verify_path}&next={_quote(result.next_url)}"
            sign_in_url = f"{frontend_base.rstrip('/')}{verify_path}"
            DjangoMagicLinkEmailAdapter().send_magic_link_email(
                email=result.email,
                sign_in_url=sign_in_url,
                site_name=site_name,
                site_domain=site_domain,
                ttl_minutes=DEFAULT_TTL_MINUTES,
            )
        except Exception:
            logger.exception("magic_link_request_email_failed email=%s", result.email)

        return generic_ok


class MagicLinkVerifyView(views.APIView):
    """`POST /identity/magic-link/verify/`

    Consumes a magic-link token. Creates the account on first click
    if none matches the token's email, then issues a JWT pair in the
    same shape ``LoginAPIView`` returns so the frontend session
    plumbing works unchanged.

    Intentionally POST-only: a GET-as-verify would let link-prefetch
    crawlers (some email clients, Slack unfurlers) silently consume
    the token before the donor clicks. The frontend reads the token
    from the URL on the verify page and posts it here.
    """

    name = "magic-link-verify"
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = []

    def get_throttles(self):
        from components.identity.api.throttles import (
            MagicLinkVerifyThrottle,
        )

        return [MagicLinkVerifyThrottle()]

    def post(self, request):
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )
        from components.identity.application.providers.magic_link_provider import (
            get_magic_link_provider,
        )
        from components.identity.application.use_cases.verify_magic_link_use_case import (
            VerifyMagicLinkError,
            VerifyMagicLinkUseCase,
        )

        OrmMagicLinkAdapter = get_magic_link_provider().store

        token_value = (request.data.get("token") or "").strip()
        result = VerifyMagicLinkUseCase(
            magic_link=OrmMagicLinkAdapter(),
            session_registry=IdentityProvider.build_session_registry(),
        ).execute(
            token_value=token_value,
            context=build_request_context(request),
        )
        if isinstance(result, VerifyMagicLinkError):
            return Response(
                {"error": result.message, "code": result.code},
                status=result.status,
            )
        return Response(
            {
                "pk": result.user_id,
                "user_id": result.user_id,
                "email": result.email,
                "username": result.username,
                "is_onboard_complete": result.is_onboard_complete,
                "is_contributor": result.is_contributor,
                "tokens": result.tokens,
                "next_url": result.next_url,
                "created_user": result.created_user,
            },
            status=status.HTTP_200_OK,
        )


# ── Token refresh (session-aware) ────────────────────────────────────


class SessionAwareTokenRefreshView(TokenRefreshView):
    """`POST /identity/token/refresh/` — stock simplejwt refresh + session touch.

    After a successful refresh, bump the login session's ``last_seen_at``
    (throttled inside the registry adapter) keyed on the SUBMITTED refresh
    token's jti — stable for the login's lifetime because refresh-token
    rotation is off. Strictly best-effort: a registry failure never fails
    the refresh.
    """

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            try:
                raw_refresh = str(request.data.get("refresh") or "").strip()
                if raw_refresh:
                    jti = str(RefreshToken(raw_refresh)["jti"])
                    from components.identity.application.providers.identity_provider import (
                        IdentityProvider,
                    )

                    IdentityProvider.build_session_registry().touch(refresh_jti=jti)
            except Exception:
                logger.exception("token_refresh_session_touch_failed")
        return response


# ── Self-serve session management + login activity (T2-S3) ──────────────


def _extract_current_sid(request) -> str | None:
    """``sid`` claim of the access token that made this request.

    ``request.auth`` is the validated simplejwt token; tokens issued
    before the session registry shipped carry no ``sid`` — return None.
    """
    token = getattr(request, "auth", None)
    if token is None:
        return None
    try:
        sid = token.get("sid")
    except (AttributeError, TypeError):
        return None
    return str(sid) if sid else None


class LoginActivityPagination(PageNumberPagination):
    page_size = 20
    # The login-activity tables paginate client-side, so the frontend pulls
    # one large page instead of chaining ?page=N "load more" requests.
    page_size_query_param = "page_size"
    max_page_size = 200


class MySessionsView(APIView):
    """`GET /identity/me/sessions/` — the caller's login sessions."""

    name = "my-sessions"
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = MySessionSerializer

    def get(self, request):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_list_my_sessions_use_case()
        sessions = use_case.execute(
            user_id=request.user.id,
            current_sid=_extract_current_sid(request),
        )
        return Response(MySessionSerializer(sessions, many=True).data, status=status.HTTP_200_OK)


class MySessionRevokeView(APIView):
    """`DELETE /identity/me/sessions/<uuid:session_id>/` — revoke ONE session.

    404 for unknown / another user's sessions (via SessionNotFoundError →
    custom exception handler); 204 for both a fresh revoke and an
    already-revoked session (idempotent).
    """

    name = "my-session-revoke"
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = EmptySerializer

    def delete(self, request, session_id=None):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_revoke_session_use_case()
        use_case.execute(
            user_id=request.user.id,
            session_id=session_id,
            email=request.user.email,
            context=build_request_context(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MySessionsRevokeOthersView(APIView):
    """`POST /identity/me/sessions/revoke-others/` — revoke all but current.

    400 (MissingSessionClaimError) when the access token has no ``sid``
    claim; otherwise ``{"revoked": N}``.
    """

    name = "my-sessions-revoke-others"
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = EmptySerializer

    def post(self, request):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_revoke_other_sessions_use_case()
        revoked = use_case.execute(
            user_id=request.user.id,
            current_sid=_extract_current_sid(request),
            email=request.user.email,
            context=build_request_context(request),
        )
        return Response({"revoked": revoked}, status=status.HTTP_200_OK)


class MyLoginActivityView(generics.ListAPIView):
    """`GET /identity/me/login-activity/` — paginated self audit trail.

    Filters: ``event_code`` (exact), ``success`` (bool), ``from`` / ``to``
    (ISO dates/datetimes, inclusive, on ``created_at``).
    """

    name = "my-login-activity"
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = LoginActivityEventSerializer
    pagination_class = LoginActivityPagination

    def get_queryset(self):
        from components.identity.application.providers.identity_provider import IdentityProvider
        from components.identity.application.queries.login_activity_query import LoginActivityQuery

        params = self.request.query_params
        use_case = IdentityProvider.build_list_login_activity_use_case()
        return use_case.execute(
            LoginActivityQuery(
                user_id=self.request.user.id,
                event_code=(params.get("event_code") or "").strip() or None,
                success=_parse_bool_param(params.get("success")),
                created_from=_parse_datetime_param(params.get("from"), "from"),
                created_to=_parse_datetime_param(params.get("to"), "to", end_of_day=True),
            )
        )


def _parse_bool_param(raw):
    """``?success=`` → bool | None. Unrecognised values are a 400."""
    if raw is None or raw == "":
        return None
    lowered = str(raw).strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    from rest_framework.exceptions import ValidationError as DRFValidationError

    raise DRFValidationError({"success": "Expected a boolean (true/false)."})


def _parse_datetime_param(raw, param, *, end_of_day=False):
    """ISO date or datetime → aware datetime | None. Invalid input is a 400.

    Bare dates expand to the start (``from``) or end (``to``) of that day
    so ``?from=2026-07-01&to=2026-07-01`` covers the whole day.
    """
    if raw is None or str(raw).strip() == "":
        return None
    from django.utils import timezone as dj_timezone
    from django.utils.dateparse import parse_date, parse_datetime
    from rest_framework.exceptions import ValidationError as DRFValidationError

    value = str(raw).strip()
    # Try the BARE-date shape first: parse_datetime() (fromisoformat-based
    # since Django 4.1) also accepts "2026-07-01" and would silently read
    # it as midnight, defeating the end-of-day expansion for ``to``.
    as_date = parse_date(value)
    if as_date is not None:
        from datetime import datetime as _datetime
        from datetime import time as _time

        parsed = _datetime.combine(as_date, _time.max if end_of_day else _time.min)
    else:
        parsed = parse_datetime(value)
        if parsed is None:
            raise DRFValidationError({param: "Expected an ISO date or datetime."})
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed)
    return parsed


def _parse_uuid_param(raw, param):
    """``?user_id=`` → UUID | None. Invalid input is a 400."""
    if raw is None or str(raw).strip() == "":
        return None
    from rest_framework.exceptions import ValidationError as DRFValidationError

    try:
        return uuid.UUID(str(raw).strip())
    except (ValueError, AttributeError, TypeError):
        raise DRFValidationError({param: "Expected a UUID."})


# ── Org-level login activity + sessions (T2-S4) ──────────────────────────
#
# Admin-only (IsWorkspaceAdmin: owner/admin ACTIVE membership, or the
# workspace owner without a membership row). Full detail — including
# ip_address and raw user_agent — is intentionally exposed to org admins
# (decided by Henry, 2026-07). The org "delete" hides the event from
# THIS workspace's view only (exclusion row → recycle bin, restorable);
# the AuthAuditEvent itself is never destroyed.
#
# Two gates on top of the admin check:
# 1. `feature.org_audit_log` — Pro-tier product flag (globally off in
#    prod, unlocked by the plan-tier layer / per-workspace rules).
# 2. The per-workspace `audit_log_enabled` admin toggle — enforced in
#    the application layer (OrgAuditVisibilityPolicy inside the three
#    org use cases → 403 with code `org_audit_log_disabled`). The
#    personal /me/* surfaces are gated by NEITHER.
_ORG_AUDIT_FLAG_KEY = "feature.org_audit_log"


class WorkspaceLoginActivityView(generics.ListAPIView):
    """`GET /identity/workspaces/<uuid:workspace_id>/login-activity/`.

    Paginated (20/page) login-ish events (``LOGIN_ACTIVITY_EVENT_CODES``)
    of the workspace's ACTIVE members, minus this workspace's exclusions.
    Filters: ``user_id``, ``event_code`` (must be in the login-ish set),
    ``success``, ``from`` / ``to`` (inclusive; bare dates expand to
    start/end of day).
    """

    name = "workspace-login-activity"
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin, RequiresFeatureFlag)
    feature_flag_key = _ORG_AUDIT_FLAG_KEY
    serializer_class = WorkspaceLoginActivityEventSerializer
    pagination_class = LoginActivityPagination

    def get_queryset(self):
        from components.identity.application.providers.identity_provider import IdentityProvider
        from components.identity.application.queries.workspace_login_activity_query import (
            WorkspaceLoginActivityQuery,
        )

        params = self.request.query_params
        event_code = (params.get("event_code") or "").strip() or None
        if event_code is not None and event_code not in LOGIN_ACTIVITY_EVENT_CODES:
            from rest_framework.exceptions import ValidationError as DRFValidationError

            raise DRFValidationError({"event_code": f"Expected one of: {', '.join(LOGIN_ACTIVITY_EVENT_CODES)}."})
        use_case = IdentityProvider.build_list_workspace_login_activity_use_case()
        return use_case.execute(
            WorkspaceLoginActivityQuery(
                workspace_id=self.kwargs["workspace_id"],
                user_id=_parse_uuid_param(params.get("user_id"), "user_id"),
                event_code=event_code,
                success=_parse_bool_param(params.get("success")),
                created_from=_parse_datetime_param(params.get("from"), "from"),
                created_to=_parse_datetime_param(params.get("to"), "to", end_of_day=True),
            )
        )


class WorkspaceSessionsView(APIView):
    """`GET /identity/workspaces/<uuid:workspace_id>/sessions/`.

    ACTIVE members' active sessions (not revoked, not expired), ordered
    by ``-last_seen_at``, capped at 200 rows.
    """

    name = "workspace-sessions"
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin, RequiresFeatureFlag)
    feature_flag_key = _ORG_AUDIT_FLAG_KEY
    serializer_class = WorkspaceSessionSerializer

    def get(self, request, workspace_id=None):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_list_workspace_sessions_use_case()
        sessions = use_case.execute(workspace_id=workspace_id)
        return Response(WorkspaceSessionSerializer(sessions, many=True).data, status=status.HTTP_200_OK)


class WorkspaceLoginActivityDeleteView(APIView):
    """`DELETE /identity/workspaces/<uuid:workspace_id>/login-activity/<int:event_id>/`.

    Hides the event from THIS workspace's org view (exclusion row →
    recycle bin, entity_type ``login_activity``); restorable from the
    bin. 204 on success AND for an already-hidden event (idempotent);
    404 (LoginActivityEventNotFoundError → custom exception handler)
    when the event doesn't belong to a member of this workspace.
    """

    name = "workspace-login-activity-delete"
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin, RequiresFeatureFlag)
    feature_flag_key = _ORG_AUDIT_FLAG_KEY
    serializer_class = EmptySerializer

    def delete(self, request, workspace_id=None, event_id=None):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_trash_workspace_login_activity_use_case()
        use_case.execute(
            workspace_id=workspace_id,
            event_id=event_id,
            deleted_by=request.user.id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceAuditLogSettingsView(APIView):
    """`GET|PATCH|PUT /identity/workspaces/<uuid:workspace_id>/audit-log-settings/`.

    Admin-only read/write of the per-workspace ``audit_log_enabled``
    visibility toggle (`{"enabled": bool}`). Intentionally NOT blocked
    by the toggle itself — an admin must see ``enabled=false`` to flip
    it back on. Still behind the `feature.org_audit_log` plan-tier flag
    like the surfaces it controls.
    """

    name = "workspace-audit-log-settings"
    permission_classes = (permissions.IsAuthenticated, IsWorkspaceAdmin, RequiresFeatureFlag)
    feature_flag_key = _ORG_AUDIT_FLAG_KEY
    serializer_class = OrgAuditLogSettingsSerializer

    def get(self, request, workspace_id=None):
        from components.identity.application.providers.identity_provider import IdentityProvider

        use_case = IdentityProvider.build_get_org_audit_log_settings_use_case()
        enabled = use_case.execute(workspace_id=workspace_id)
        return Response({"enabled": enabled}, status=status.HTTP_200_OK)

    def patch(self, request, workspace_id=None):
        return self._update(request, workspace_id)

    def put(self, request, workspace_id=None):
        return self._update(request, workspace_id)

    def _update(self, request, workspace_id):
        from components.identity.application.providers.identity_provider import IdentityProvider

        serializer = OrgAuditLogSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        use_case = IdentityProvider.build_set_org_audit_log_settings_use_case()
        enabled = use_case.execute(
            workspace_id=workspace_id,
            enabled=serializer.validated_data["enabled"],
            changed_by=request.user.id,
        )
        return Response({"enabled": enabled}, status=status.HTTP_200_OK)
