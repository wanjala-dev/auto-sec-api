"""Coverage for the feature.social_feed scope-freeze gate.

See docs/plans/GO_TO_MARKET_PLAN.md §6 and
docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 2.

When feature.social_feed is off (prod default), the standalone social
surfaces under /social/ return 403. Messaging (extracted to
components.messaging, mounted at /messaging/), notifications, and
workspace-internal updates remain fully available.

Scope note: this PR gates only /social/*. The user-engagement routes
mounted under /identity/ (posts/<pk>/like, profile/<pk>/followers/,
etc.) reuse the same view classes, so they inherit the gate too —
that's intentional: they're part of the consumer-social product.
"""

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]


FLAG_KEY = "feature.social_feed"


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


# ---------------------------------------------------------------------------
# Flag off ⇒ 403 on every /social/ surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/social/"),
        ("post", "/social/"),
        ("get", "/social/1/"),
        ("get", "/social/comment"),
        ("get", "/social/comment/1/"),
        ("get", "/social/tag"),
        ("get", "/social/tag/1/"),
    ],
)
def test_social_surface_blocked_when_flag_off(api_client, user_factory, method, url):
    _set_flag(False)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 403, (
        f"{method.upper()} {url} should 403 when feature.social_feed is off "
        f"(got {response.status_code})"
    )


# ---------------------------------------------------------------------------
# Flag on ⇒ permission layer permits
# ---------------------------------------------------------------------------


def test_social_list_permission_passes_when_flag_on(api_client, user_factory):
    _set_flag(True)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get("/social/")

    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Messaging and notifications are unaffected — they live in other contexts
# ---------------------------------------------------------------------------


def test_messaging_unaffected_when_social_flag_off(api_client, user_factory):
    _set_flag(False)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get("/messaging/unread/")

    assert response.status_code != 403


def test_notifications_unaffected_when_social_flag_off(api_client, user_factory):
    _set_flag(False)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get("/notifications/unread-count/")

    assert response.status_code != 403
