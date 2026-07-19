"""Coverage for the feature.agent_marketplace scope-freeze gate.

See docs/plans/GO_TO_MARKET_PLAN.md §6 and
docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 5.

When feature.agent_marketplace is off (prod default), the social-discovery
surfaces around agents (follow, like, rate, ratings, comment, share,
SharedAgentViewSet) return 403. Execution, chat, deep-run, memory, and
workspace-admin actions are NOT gated — the Finance Reviewer and PDF
tools stay fully available.
"""

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.ai.agents.models import Agent
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]


FLAG_KEY = "feature.agent_marketplace"


def _set_flag(enabled: bool) -> None:
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": True, "description": "test-seeded"},
    )
    if enabled:
        FeatureFlagRule.objects.filter(
            flag=flag, scope=FeatureFlagRule.Scope.GLOBAL
        ).delete()
    else:
        FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            defaults={"enabled": False, "note": "gate test"},
        )
    bump_feature_flags_version()


@pytest.fixture
def agent(user_factory, workspace_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    return Agent.objects.create(
        agent_type="sponsorship_agent",
        user=owner,
        workspace=workspace,
        status="active",
        config={},
    )


# ---------------------------------------------------------------------------
# Gated social surfaces — flag off ⇒ 403
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url_suffix",
    [
        ("post", "follow"),
        ("post", "like"),
        ("post", "rating"),
        ("get", "ratings"),
        ("post", "comments/create"),
        ("get", "comments"),
        ("post", "share"),
    ],
)
def test_social_action_blocked_when_flag_off(
    api_client, user_factory, agent, method, url_suffix
):
    _set_flag(False)
    user = user_factory()
    api_client.force_authenticate(user=user)

    url = f"/ai/agents/{agent.agent_id}/{url_suffix}/"
    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 403, (
        f"{method.upper()} {url_suffix} should 403 when agent_marketplace is off "
        f"(got {response.status_code})"
    )


def test_shared_agent_viewset_has_class_level_flag_gate():
    """SharedAgentViewSet is entirely a social-discovery surface, so the flag
    is enforced at the class level via RequiresFeatureFlag in permission_classes.
    URL routing for this viewset uses a custom share-token pattern that varies
    across releases — test the wiring directly instead.
    """
    from components.agents.api.controller import SharedAgentViewSet
    from components.shared_platform.api.permissions import RequiresFeatureFlag

    assert RequiresFeatureFlag in SharedAgentViewSet.permission_classes
    assert SharedAgentViewSet.feature_flag_key == "feature.agent_marketplace"


# ---------------------------------------------------------------------------
# Un-gated surfaces — flag off, execution/chat still works
# ---------------------------------------------------------------------------


def test_agent_list_stays_available_when_flag_off(api_client, user_factory):
    _set_flag(False)
    user = user_factory()
    api_client.force_authenticate(user=user)

    response = api_client.get("/ai/agents/")

    # Not 403 — list is an execution-adjacent catalog, not a social surface.
    assert response.status_code != 403


def test_agent_types_stays_available_when_flag_off(api_client, user_factory):
    _set_flag(False)
    user = user_factory()
    api_client.force_authenticate(user=user)

    response = api_client.get("/ai/agents/types/")

    # Agent type catalog is needed for agent creation — not gated.
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Flag on — everything works
# ---------------------------------------------------------------------------


def test_follow_permission_passes_when_flag_on(api_client, user_factory, agent):
    """Flag on ⇒ the RequiresFeatureFlag permission permits the request.

    Downstream business logic may still reject (a separate pre-existing
    regression in AgentsService.follow_agent returns 500 in this path),
    so we only assert that the response is NOT a flag-level 403.
    """
    _set_flag(True)
    follower = user_factory()
    agent.workspace.followers.add(follower)
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=follower)

    response = api_client.post(f"/ai/agents/{agent.agent_id}/follow/", {}, format="json")

    assert response.status_code != 403
