from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.contrib.sites.models import Site
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from components.payments.api.requests.team_plan_checkout_request import (
    TeamPlanCheckoutRequest,
)
from components.workspace.application.facades.workspace_facade import user_is_workspace_member

logger = logging.getLogger(__name__)


def _get_team_plan_billing_service():
    from components.payments.application.providers.team_plan_billing_provider import (
        TeamPlanBillingProvider,
    )
    return TeamPlanBillingProvider().build_service()


def _get_team_plan_webhook_service():
    from components.payments.application.providers.team_plan_webhook_provider import (
        TeamPlanWebhookProvider,
    )
    return TeamPlanWebhookProvider().build_service()


def _get_workspace_billing_service():
    from components.payments.application.providers.workspace_billing_provider import (
        WorkspaceBillingProvider,
    )
    return WorkspaceBillingProvider().build_service()


def _require_workspace_member(request, workspace: Workspace) -> None:
    if not user_is_workspace_member(request.user, workspace):
        raise PermissionDenied(
            "You must belong to the organization to perform this action."
        )


def _require_workspace_admin(request, workspace: Workspace) -> None:
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
    WorkspaceMembership = get_workspaces_models_provider().WorkspaceMembership

    if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
        return
    if str(workspace.workspace_owner_id) == str(request.user.id):
        return
    if WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=request.user,
        status=WorkspaceMembership.Status.ACTIVE,
        role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
    ).exists():
        return
    raise PermissionDenied("You must be an organization admin to manage billing.")


def _refuse_during_impersonation(request, workspace: Workspace) -> None:
    """Block money mutations when an impersonation session would grant
    the actor admin access they don't otherwise have on this workspace.

    Money flows must trace to a real authenticated actor with real
    privilege. If Henry is impersonating as admin on a customer's
    workspace where he has no real membership, money is locked. If
    he's previewing his OWN org as contributor (he's the real owner),
    money stays open — the impersonation is a UX preview, not a
    privilege grant. See SupportImpersonationSession.
    """
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
    WorkspaceMembership = get_workspaces_models_provider().WorkspaceMembership

    impersonating = WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=request.user,
        status=WorkspaceMembership.Status.ACTIVE,
        is_impersonation=True,
    ).exists()
    if not impersonating:
        return

    # Real (non-impersonation) admin/owner role on this workspace? If
    # yes, the impersonation isn't escalating money powers — block-by-
    # default would just frustrate the actor's legitimate workflow.
    has_real_admin = (
        str(workspace.workspace_owner_id) == str(request.user.id)
        or WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user,
            status=WorkspaceMembership.Status.ACTIVE,
            is_impersonation=False,
            role__in=[
                WorkspaceMembership.Role.OWNER,
                WorkspaceMembership.Role.ADMIN,
            ],
        ).exists()
    )
    if has_real_admin:
        return

    raise PermissionDenied(
        "Money mutations are disabled during a support impersonation "
        "session on a workspace you don't already administer. End the "
        "session first or use Django admin."
    )


def _require_team_member(request, team: Team) -> None:
    if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
        return
    if str(team.workspace.workspace_owner_id) == str(request.user.id):
        return
    if not team.members.filter(id=request.user.id).exists():
        raise PermissionDenied("You must be a member of this team.")


def _resolve_workspace_admin_request(request) -> Workspace | Response:
    from components.identity.application.providers.users_models_provider import get_users_models_provider
    UserProfile = get_users_models_provider().UserProfile
    from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
    Workspace = get_workspaces_models_provider().Workspace

    workspace_id = request.data.get("workspace") or request.query_params.get("workspace")
    if not workspace_id and request.user.is_authenticated:
        profile = UserProfile.objects.filter(user=request.user).only("active_workspace_id").first()
        workspace_id = profile.active_workspace_id if profile else None
    if not workspace_id:
        return Response(
            {"error": "Organization identifier is required."},
            status=status.HTTP_404_NOT_FOUND,
        )
    workspace = Workspace.objects.filter(id=workspace_id).first()
    if not workspace:
        return Response({"error": "Organization not found."}, status=status.HTTP_404_NOT_FOUND)
    _require_workspace_admin(request, workspace)
    return workspace


def _resolve_billing_plan(plan_value) -> "Plan | None":
    from components.team.application.providers.team_models_provider import get_team_models_provider
    Plan = get_team_models_provider().Plan

    if isinstance(plan_value, int):
        return Plan.objects.filter(id=plan_value).first()
    if isinstance(plan_value, str) and plan_value.isdigit():
        return Plan.objects.filter(id=int(plan_value)).first()
    if plan_value:
        return Plan.objects.filter(title__iexact=str(plan_value)).first()
    return None


def _build_team_plan_checkout_request(request) -> TeamPlanCheckoutRequest:
    return TeamPlanCheckoutRequest(
        plan=request.data.get("plan") or request.query_params.get("plan"),
        plan_id=request.data.get("plan_id") or request.query_params.get("plan_id"),
        workspace_id=request.data.get("workspace") or request.query_params.get("workspace"),
        team_id=request.data.get("team") or request.data.get("team_id"),
        success_url=request.data.get("success_url"),
        cancel_url=request.data.get("cancel_url"),
        proration_behavior=request.data.get("proration_behavior"),
        scheme=getattr(request, "scheme", "https"),
        site_domain=getattr(request, "_billing_site_domain", None),
    )


def _resolve_customer_name(profile: UserProfile) -> str | None:
    customer_name = getattr(profile, "name", None)
    if customer_name:
        return customer_name
    name_parts = [
        getattr(profile.user, "first_name", ""),
        getattr(profile.user, "last_name", ""),
    ]
    return " ".join(part for part in name_parts if part).strip() or None


def _build_checkout_urls(
    *,
    checkout_request: TeamPlanCheckoutRequest,
    plan: Plan,
    team: Team | None,
) -> tuple[str, str]:
    # The client (billing settings page) normally passes explicit success/cancel
    # URLs from its own origin. When it doesn't, the fallback MUST target the
    # FRONTEND — site_domain here is request.get_host(), i.e. the API host
    # (api.wanjala.art), so a Stripe redirect built from it would dead-end on the
    # backend. resolve_frontend_base_url() is the single source of truth (honours
    # FRONTEND_URL → app.octopusintl.org).
    from components.shared_platform.infrastructure.services.core_utils import (
        resolve_frontend_base_url,
    )

    frontend_base = resolve_frontend_base_url().rstrip("/")
    success_url = checkout_request.success_url or (
        f"{frontend_base}/subscriptions/pricing/twotier/?session_id={{CHECKOUT_SESSION_ID}}&plan={plan.title}"
        + (f"&team={team.id}" if team else "")
    )
    cancel_url = checkout_request.cancel_url or f"{frontend_base}/subscriptions/pricing/twotier/"
    return success_url, cancel_url


def _append_query(base_url: str, params: dict) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    existing_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing_params.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing_params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _resolve_frontend_url(request, override: str | None = None) -> str:
    if override:
        return override
    try:
        site = Site.objects.get_current(request)
        domain = site.domain.rstrip("/")
        scheme = "https" if request.is_secure() else "http"
        return f"{scheme}://{domain}/"
    except Site.DoesNotExist:
        return request.build_absolute_uri("/")
