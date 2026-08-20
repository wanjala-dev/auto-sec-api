"""Coverage for the feature.social_feed scope-freeze gate.

See docs/plans/GO_TO_MARKET_PLAN.md §6 and
docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 2.

When feature.social_feed is off (prod default), the flag-gated feed
interaction surfaces under /social/ return 403. Messaging (extracted to
components.messaging, mounted at /messaging/), notifications, and
workspace-internal updates remain fully available.

Scope note: this file used to parametrize the legacy CRUD routes (``/social/``,
``/social/<pk>/``, ``/social/comment``, ``/social/comment/<pk>/``). Those routes
were RETIRED 2026-08-19 — a route that does not exist cannot be gated, and
their absence is pinned by ``test_legacy_social_crud_retired.py`` instead. The
gate now covers the routes that actually survive.

Its old docstring also claimed the user-engagement routes under ``/identity/``
reuse these view classes and inherit the gate. That was stale: ``/identity/``
imports nothing from ``components.social.api.controller`` (verified by grep),
and those routes no longer exist.
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
        FeatureFlagRule.objects.filter(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL).delete()
    else:
        FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            defaults={"enabled": False, "note": "gate test"},
        )
    bump_feature_flags_version()


# ---------------------------------------------------------------------------
# Flag off ⇒ 403 on every flag-gated /social/ surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("post", "/social/posts/1/like/"),
        ("get", "/social/posts/1/comments/"),
        ("post", "/social/posts/1/comments/"),
    ],
)
def test_social_surface_blocked_when_flag_off(api_client, user_factory, method, url):
    _set_flag(False)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 403, (
        f"{method.upper()} {url} should 403 when feature.social_feed is off (got {response.status_code})"
    )


# ---------------------------------------------------------------------------
# Flag on ⇒ permission layer permits (404 for the absent post, never 403)
# ---------------------------------------------------------------------------


def test_social_feed_permission_passes_when_flag_on(api_client, user_factory):
    _set_flag(True)
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get("/social/posts/1/comments/")

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
