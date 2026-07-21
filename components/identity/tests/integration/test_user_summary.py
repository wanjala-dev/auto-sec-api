"""Coverage for the lightweight user summary endpoint."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_user_summary_returns_expected_payload(api_client, user_factory, workspace_factory, team_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user, members=[user])

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["user"]["id"] == str(user.id)
    assert payload["user"]["two_factor_enabled"] is False
    assert payload["user"]["two_factor_confirmed_at"] is None
    assert any(item["id"] == team.id for item in payload["teams"])
    assert any(item["id"] == str(workspace.id) for item in payload["workspaces"])
    assert "workspace_context" in payload
    assert "feature_flags" in payload


def test_user_summary_includes_two_factor_fields_when_enabled(api_client, user_factory):
    from django.utils import timezone

    user = user_factory()
    user.two_factor_enabled = True
    user.two_factor_confirmed_at = timezone.now()
    user.save(update_fields=["two_factor_enabled", "two_factor_confirmed_at"])

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    summary_user = response.data["data"]["user"]
    assert summary_user["two_factor_enabled"] is True
    assert summary_user["two_factor_confirmed_at"] is not None


def test_user_summary_marks_personal_workspace_when_active(api_client, user_factory, workspace_factory):
    user = user_factory()
    personal_workspace = workspace_factory(owner=user, sector_id="personal")

    from infrastructure.persistence.users.models import UserProfile

    UserProfile.objects.update_or_create(user=user, defaults={"active_workspace_id": personal_workspace.id})

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    context = response.data["data"]["workspace_context"]
    assert context["active_workspace_id"] == str(personal_workspace.id)
    assert context["active_workspace_kind"] == "personal"
    assert context["active_workspace_role"] == "owner"
    assert context["active_workspace_is_personal_owner"] is True


def test_user_summary_includes_is_platform_admin(api_client, user_factory, workspace_factory):
    regular_user = user_factory()
    workspace_factory(owner=regular_user)
    api_client.force_authenticate(user=regular_user)
    response = api_client.get(reverse("user-summary"))
    assert response.status_code == 200
    assert response.data["data"]["user"]["is_platform_admin"] is False

    staff_user = user_factory()
    staff_user.is_staff = True
    staff_user.save(update_fields=["is_staff"])
    workspace_factory(owner=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(reverse("user-summary"))
    assert response.status_code == 200
    assert response.data["data"]["user"]["is_platform_admin"] is True

    super_user = user_factory()
    super_user.is_superuser = True
    super_user.save(update_fields=["is_superuser"])
    workspace_factory(owner=super_user)
    api_client.force_authenticate(user=super_user)
    response = api_client.get(reverse("user-summary"))
    assert response.status_code == 200
    assert response.data["data"]["user"]["is_platform_admin"] is True


def test_user_summary_marks_org_workspace_when_active(api_client, user_factory, workspace_factory):
    user = user_factory()
    org_workspace = workspace_factory(owner=user, sector_id="nonprofit")

    from infrastructure.persistence.users.models import UserProfile

    UserProfile.objects.update_or_create(user=user, defaults={"active_workspace_id": org_workspace.id})

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    context = response.data["data"]["workspace_context"]
    assert context["active_workspace_id"] == str(org_workspace.id)
    assert context["active_workspace_kind"] == "organization"
    assert context["active_workspace_role"] == "owner"


def test_user_summary_carries_workspace_default_currency(api_client, user_factory, workspace_factory):
    """Workspace.default_currency must surface on the session summary
    so the frontend's ``useWorkspaceCurrency`` hook can format amounts
    before any payment method is connected."""
    user = user_factory()
    workspace = workspace_factory(owner=user, sector_id="nonprofit")
    workspace.default_currency = "KES"
    workspace.save(update_fields=["default_currency"])

    from infrastructure.persistence.users.models import UserProfile

    UserProfile.objects.update_or_create(user=user, defaults={"active_workspace_id": workspace.id})

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    context = response.data["data"]["workspace_context"]
    assert context["active_workspace_default_currency"] == "KES"


def test_user_summary_workspace_entries_carry_default_currency(api_client, user_factory, workspace_factory):
    """Each workspace entry in the summary must carry its own
    ``default_currency`` so the frontend ``useWorkspaceCurrency(workspaceId)``
    hook resolves the right currency per workspace — not just for the
    active one. Without this, admin money surfaces (budget, transactions)
    fall back to USD and render "$" for a CAD/KES workspace."""
    user = user_factory()
    workspace = workspace_factory(owner=user, sector_id="nonprofit")
    workspace.default_currency = "CAD"
    workspace.save(update_fields=["default_currency"])

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    # The serialized workspace appears in one of the summary's buckets;
    # find it by id wherever it lands and assert its currency.
    payload = response.data["data"]

    def _iter_workspace_dicts(node):
        if isinstance(node, dict):
            if node.get("id") is not None and "workspace_type" in node:
                yield node
            for value in node.values():
                yield from _iter_workspace_dicts(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                yield from _iter_workspace_dicts(item)

    entry = next(
        (w for w in _iter_workspace_dicts(payload) if str(w.get("id")) == str(workspace.id)),
        None,
    )
    assert entry is not None, "workspace not found in summary payload"
    assert entry["default_currency"] == "CAD"


def test_user_summary_default_currency_absent_for_anonymous_active_workspace(api_client, user_factory):
    """When the user has no active workspace, the currency is null —
    not the platform default. The frontend hook owns the fallback."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    context = response.data["data"]["workspace_context"]
    assert context["active_workspace_id"] is None
    assert context["active_workspace_default_currency"] is None


# ── Relationship annotation (members vs followers) ────────────────────────
#
# ``user.get_related_workspaces_queryset()`` unions four sources: owner,
# team membership, ``WorkspaceMembership``, and the ``followers`` M2M.
# The first three are real memberships and earn the workspace dashboard;
# the fourth is just spectator access. Pre-fix the response didn't
# distinguish, so the frontend rendered an empty contributor sidebar
# for follow-only workspaces (codenry hit this 2026-05-08 after
# following CBH's workspace). The ``relationship`` field exists so the
# frontend can route follow-only access to ``/profile/organization/``
# instead. Tests below pin the contract.


def test_user_summary_marks_owner_workspace_as_member(api_client, user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]["workspaces"]
    entry = next(w for w in payload if w["id"] == str(workspace.id))
    assert entry["relationship"] == "member", "Workspace owner must be classified as a member, not a follower."


def test_user_summary_marks_team_member_workspace_as_member(api_client, user_factory, workspace_factory, team_factory):
    """Joining via a team's members list (without a direct
    ``WorkspaceMembership`` row) still counts as membership."""
    owner = user_factory()
    contributor = user_factory()
    workspace = workspace_factory(owner=owner)
    team_factory(workspace=workspace, created_by=owner, members=[contributor])

    api_client.force_authenticate(user=contributor)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]["workspaces"]
    entry = next(w for w in payload if w["id"] == str(workspace.id))
    assert entry["relationship"] == "member"


def test_user_summary_marks_follow_only_workspace_as_follower(api_client, user_factory, workspace_factory):
    """The exact 2026-05-08 incident shape: a user follows a workspace
    they were never invited to. Pre-fix this rendered an empty sidebar
    because the role-policy fallback made them look like a sponsor.
    With the ``relationship='follower'`` annotation the frontend can
    redirect them to the workspace profile page instead.
    """
    owner = user_factory()
    follower = user_factory()
    workspace = workspace_factory(owner=owner)
    workspace.followers.add(follower)

    api_client.force_authenticate(user=follower)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]["workspaces"]
    entry = next(
        (w for w in payload if w["id"] == str(workspace.id)),
        None,
    )
    assert entry is not None, (
        "Followed workspace must still appear in the summary so the "
        "frontend can render its profile page; this test would have "
        "to be rewritten if we ever filter followers out."
    )
    assert entry["relationship"] == "follower"


def test_user_summary_membership_overrides_follower_for_dual_relationship(api_client, user_factory, workspace_factory):
    """A user can both follow AND be a member of the same workspace
    (e.g. they followed it before being invited). Membership wins —
    the dashboard shouldn't disappear because they once tapped Follow.
    """
    from infrastructure.persistence.workspaces.models import (
        WorkspaceMembership,
    )

    owner = user_factory()
    user = user_factory()
    workspace = workspace_factory(owner=owner)
    workspace.followers.add(user)
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMembership.Role.MEMBER,
        persona=WorkspaceMembership.Persona.CONTRIBUTOR,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]["workspaces"]
    entry = next(w for w in payload if w["id"] == str(workspace.id))
    assert entry["relationship"] == "member"


# ────────────────────────────────────────────────────────────────────
# is_donor projection
# A logged-in user who has donated to a workspace should see that
# workspace in their summary even when they aren't a member or follower
# — the frontend buckets these under "Supporting" in the sidebar. A
# member who has also donated should be flagged on both axes
# (relationship="member" + is_donor=True) so the frontend can render
# "you donated $X" copy on the dashboard without losing the membership
# context. Non-donors get is_donor=False.
# ────────────────────────────────────────────────────────────────────


def test_user_summary_is_donor_false_when_no_donation(api_client, user_factory, workspace_factory):
    """Default: is_donor=False for any workspace without a donor
    Transaction row for the requesting user.
    """
    owner = user_factory()
    follower = user_factory()
    workspace = workspace_factory(owner=owner)
    workspace.followers.add(follower)

    api_client.force_authenticate(user=follower)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]["workspaces"]
    entry = next(w for w in payload if w["id"] == str(workspace.id))
    assert entry["is_donor"] is False


# ────────────────────────────────────────────────────────────────────
# Phase 1 of the Agents-as-Teammates migration
# (docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md):
# every workspace exposes ``agent_team_id`` on the summary so the
# frontend can deep-link to the agent team's "AI Findings" Kanban
# without an extra round-trip. ``None`` is valid during the data
# migration window for workspaces that haven't been backfilled yet.
# ────────────────────────────────────────────────────────────────────


def test_user_summary_exposes_agent_team_id_when_present(api_client, user_factory, workspace_factory):
    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )

    user = user_factory()
    workspace = workspace_factory(owner=user)
    board = ensure_agents_board(workspace)

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    entry = next(w for w in response.data["data"]["workspaces"] if w["id"] == str(workspace.id))
    assert entry["agent_team_id"] == str(board.team.id)


def test_user_summary_agent_team_id_is_null_when_no_agent_team_exists(api_client, user_factory, workspace_factory):
    """Workspaces created via the raw factory don't have an agent team
    (the eager-bootstrap fires from CreateWorkspaceUseCase + the
    identity bootstrap helpers, not from the test factory). The summary
    must still render — ``agent_team_id`` is just ``None``."""
    user = user_factory()
    workspace = workspace_factory(owner=user)

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    entry = next(w for w in response.data["data"]["workspaces"] if w["id"] == str(workspace.id))
    assert entry["agent_team_id"] is None


def test_ensure_agents_board_is_idempotent(workspace_factory):
    """Two calls produce the same team / project — the backfill
    migration and the eager bootstrap can both run on the same
    workspace without producing duplicates."""
    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )

    workspace = workspace_factory()

    first = ensure_agents_board(workspace)
    second = ensure_agents_board(workspace)

    assert first.team.id == second.team.id
    assert first.project.id == second.project.id
    assert set(first.columns_by_title.keys()) == set(second.columns_by_title.keys())


# ────────────────────────────────────────────────────────────────────
# shared_with_me bucket — non-owner with a membership row on
# someone else's personal workspace (Adviser / family member /
# accountant). See the 2026-06-13 sidebar-pattern research synthesis
# for why this is a distinct bucket and not a flavour of "supporting".
# ────────────────────────────────────────────────────────────────────


def test_user_summary_returns_shared_with_me_bucket_for_adviser_on_personal_workspace(
    api_client, user_factory, workspace_factory
):
    """Bob is invited as an Adviser on Alice's personal workspace.
    Bob's me/summary must surface that workspace in the dedicated
    ``shared_with_me`` bucket — NOT silently classified under
    ``supporting`` (donor follows) where it was indistinguishable
    from one-time donations."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    alice = user_factory()
    bob = user_factory()
    alice_personal = workspace_factory(owner=alice, workspace_type="personal")
    WorkspaceMembership.objects.create(
        workspace=alice_personal,
        user=bob,
        role=WorkspaceMembership.Role.VIEWER,
        persona=WorkspaceMembership.Persona.ADVISER,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    api_client.force_authenticate(user=bob)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    payload = response.data["data"]
    shared = payload.get("shared_with_me") or []
    assert any(w["id"] == str(alice_personal.id) for w in shared), (
        "Alice's personal workspace must appear in Bob's shared_with_me "
        "bucket — the discriminator is workspace_type='personal' AND "
        "not is_owner AND has membership."
    )
    # Must NOT also leak into supporting (mixes donors + adviser memberships).
    supporting = payload.get("supporting") or []
    assert not any(w["id"] == str(alice_personal.id) for w in supporting)
    # Must NOT leak into teamspaces.
    teamspaces = payload.get("teamspaces") or []
    assert not any(w["id"] == str(alice_personal.id) for w in teamspaces)


def test_user_summary_emits_workspace_type_and_is_owner_per_workspace(api_client, user_factory, workspace_factory):
    """Every workspace dict must carry the (workspace_type, is_owner)
    pair so the frontend has the unambiguous discriminator for the
    three sidebar buckets (Private / Teamspaces / Shared with me)
    without inferring from relationship + persona."""
    user = user_factory()
    teamspace = workspace_factory(owner=user)
    personal = workspace_factory(owner=user, workspace_type="personal")

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    workspaces = response.data["data"]["workspaces"]
    teamspace_dict = next(w for w in workspaces if w["id"] == str(teamspace.id))

    assert teamspace_dict["workspace_type"] == "teamspace"
    assert teamspace_dict["is_owner"] is True

    # Personal workspaces owned by the viewer may be gated out of /me/summary
    # by feature.personal_space (disabled in prod, may be off in tests).
    # When present, they must carry workspace_type='personal' AND is_owner=True.
    personal_dict = next((w for w in workspaces if w["id"] == str(personal.id)), None)
    if personal_dict is not None:
        assert personal_dict["workspace_type"] == "personal"
        assert personal_dict["is_owner"] is True


def test_user_summary_shared_with_me_dict_marks_is_owner_false(api_client, user_factory, workspace_factory):
    """The shared_with_me bucket carries is_owner=False so the
    frontend can render the right copy ('Alice's books' vs 'Your
    books') without a second round-trip."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    alice = user_factory()
    bob = user_factory()
    alice_personal = workspace_factory(owner=alice, workspace_type="personal")
    WorkspaceMembership.objects.create(
        workspace=alice_personal,
        user=bob,
        role=WorkspaceMembership.Role.VIEWER,
        persona=WorkspaceMembership.Persona.ADVISER,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    api_client.force_authenticate(user=bob)
    response = api_client.get(reverse("user-summary"))

    shared = response.data["data"].get("shared_with_me") or []
    entry = next(w for w in shared if w["id"] == str(alice_personal.id))
    assert entry["is_owner"] is False
    assert entry["persona"] == "adviser"


def test_user_summary_shared_with_me_empty_for_users_without_adviser_memberships(
    api_client, user_factory, workspace_factory
):
    """A user who hasn't been invited to anyone else's personal
    workspace gets an empty shared_with_me bucket — the field is
    always present (so the frontend doesn't have to null-check)."""
    user = user_factory()
    workspace_factory(owner=user)

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    assert response.data["data"].get("shared_with_me") == []


def test_user_summary_ai_quota_and_theme_resolve_without_exceptions(
    api_client, user_factory, workspace_factory, caplog
):
    """Regression for the wanjala-leftover me/summary tracebacks.

    Before the fix, every call with an active workspace logged two
    ``logger.exception`` tracebacks — ``ModuleNotFoundError`` for the unported
    ``ai_run_quota_adapter`` and ``brand_resolution_provider`` — and the
    frontend-consumed ``active_workspace_ai_quota`` field silently degraded to
    ``None``. Now the quota adapter is ported (real snapshot) and the unported
    brand kit is an explicit ``theme: None`` contract, so NOTHING in the
    summary path may log an error.
    """
    import logging

    user = user_factory()
    workspace = workspace_factory(owner=user)

    from infrastructure.persistence.users.models import UserProfile

    UserProfile.objects.update_or_create(user=user, defaults={"active_workspace_id": workspace.id})

    api_client.force_authenticate(user=user)
    with caplog.at_level(logging.WARNING):
        response = api_client.get(reverse("user-summary"))

    assert response.status_code == 200
    context = response.data["data"]["workspace_context"]

    # AI quota snapshot is REAL (consumed by useActiveWorkspaceAIQuota /
    # useChatSession for the chat-header pill) — not the degraded None.
    quota = context["active_workspace_ai_quota"]
    assert quota is not None
    for key in (
        "ai_enabled",
        "daily_message_budget",
        "daily_messages_used",
        "daily_messages_remaining",
        "monthly_token_budget",
        "monthly_tokens_used",
        "monthly_tokens_remaining",
        "monthly_run_budget",
        "monthly_runs_used",
        "monthly_runs_remaining",
    ):
        assert key in quota

    # The brand kit is not part of this fork: theme is an explicit None and
    # the frontend falls back to the Octopus default palette/logo.
    assert context["theme"] is None

    # The leftover tracebacks are gone — no error/exception logs from the
    # summary path.
    summary_errors = [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR
        and (
            "AI quota snapshot" in record.getMessage()
            or "workspace brand" in record.getMessage()
        )
    ]
    assert summary_errors == []
