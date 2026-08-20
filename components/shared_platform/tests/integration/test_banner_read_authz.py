"""Read authorization for ``/announcements/banners/`` (``BannerViewSet``).

The write verbs on this viewset are correctly gated —
``get_permissions()`` returns ``IsAdminUser`` for everything except
``list``/``retrieve``, and POST/PATCH/DELETE were confirmed **401** anonymously
against the live cluster. That half is right and these tests pin it so a
refactor cannot quietly loosen it.

The read half is the defect. ``list``/``retrieve`` return ``AllowAny()``, and
``get_queryset()`` builds its scope filter EXCLUSIVELY from client-supplied
query parameters — ``?scope``, ``?workspace``, ``?user``, ``?include_inactive``
— never once consulting ``request.user``. Confirmed live with no
``Authorization`` header: ``GET /announcements/banners/`` and every filter
variant returned **200**, and an authenticated control returned byte-identical
results, proving the read path never consults the caller.

Nothing was disclosed in that environment only because the ``Banner`` table is
empty. The control failure is total, not partial. The moment a scoped banner
exists:

* ``?scope=user&user=<uuid>`` hands an anonymous caller another user's private
  banners — and ``BannerSerializer`` exposes ``user_email``;
* ``?scope=workspace&workspace=<uuid>`` does the same across tenants;
* ``?scope=all&include_inactive=true`` drops BOTH the scope filter and the
  active-window filter, returning every banner of every scope for every
  tenant, including scheduled-but-not-yet-live and expired ones.

The fix derives scope from the caller instead of trusting the client: reads
require authentication; ``?user`` may only ever be the caller's own id;
``?workspace`` must be a workspace the caller holds an ACTIVE membership in;
``include_inactive`` is staff-only. A rejected parameter narrows the result —
it never errors — so the pre-existing frontend call (which sends ``?seed=``,
a parameter this view has never read) keeps working unchanged.
"""

from __future__ import annotations

import uuid

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

pytestmark = [pytest.mark.django_db]

URL = "/announcements/banners/"


def _banner_model():
    return django_apps.get_model("broadcast", "Banner")


def _membership_model():
    return django_apps.get_model("workspaces", "WorkspaceMembership")


def _join(workspace, user):
    Membership = _membership_model()
    return Membership.objects.create(
        workspace=workspace,
        user=user,
        role="viewer",
        status=Membership.Status.ACTIVE,
    )


def _staff(user_factory):
    """``user_factory`` wraps ``create_user``, which rejects ``is_staff``."""
    user = user_factory()
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


def _ids(response):
    payload = response.data
    rows = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
    return {row["id"] for row in rows}


class TestAnonymousReadIsRefused:
    def test_anonymous_list_is_refused(self, api_client):
        assert api_client.get(URL).status_code == 401

    def test_anonymous_retrieve_is_refused(self, api_client, user_factory):
        banner = _banner_model().objects.create(message="private", scope="user", user=user_factory())

        response = api_client.get(f"{URL}{banner.pk}/")

        assert response.status_code == 401

    def test_anonymous_user_scoped_probe_is_refused(self, api_client, user_factory):
        """The headline exploit: name a user id, read their private banners."""
        victim = user_factory()
        _banner_model().objects.create(message="private", scope="user", user=victim)

        response = api_client.get(f"{URL}?scope=user&user={victim.id}")

        assert response.status_code == 401


class TestClientSuppliedScopeCannotWiden:
    def test_another_users_banner_is_not_returned(self, api_client, user_factory):
        victim = user_factory()
        hidden = _banner_model().objects.create(message="private", scope="user", user=victim)
        caller = user_factory()
        api_client.force_authenticate(user=caller)

        response = api_client.get(f"{URL}?scope=user&user={victim.id}")

        assert response.status_code == 200
        assert hidden.pk not in _ids(response)

    def test_another_tenants_workspace_banner_is_not_returned(self, api_client, user_factory, workspace_factory):
        foreign = workspace_factory()
        hidden = _banner_model().objects.create(message="theirs", scope="workspace", workspace=foreign)
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"{URL}?scope=workspace&workspace={foreign.id}")

        assert response.status_code == 200
        assert hidden.pk not in _ids(response)

    def test_scope_all_does_not_dump_every_scope(self, api_client, user_factory, workspace_factory):
        """``scope=all`` skipped the scope filter entirely."""
        foreign_user_banner = _banner_model().objects.create(message="private", scope="user", user=user_factory())
        foreign_ws_banner = _banner_model().objects.create(
            message="theirs", scope="workspace", workspace=workspace_factory()
        )
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"{URL}?scope=all")

        assert response.status_code == 200
        returned = _ids(response)
        assert foreign_user_banner.pk not in returned
        assert foreign_ws_banner.pk not in returned

    def test_include_inactive_is_staff_only(self, api_client, user_factory):
        """Unpublished and expired banners are pre-announcement material."""
        caller = user_factory()
        scheduled = _banner_model().objects.create(
            message="not live yet",
            scope="user",
            user=caller,
            starts_at=timezone.now() + timezone.timedelta(days=7),
        )
        api_client.force_authenticate(user=caller)

        response = api_client.get(f"{URL}?include_inactive=true")

        assert response.status_code == 200
        assert scheduled.pk not in _ids(response)

    def test_staff_keeps_include_inactive(self, api_client, user_factory):
        staff = _staff(user_factory)
        scheduled = _banner_model().objects.create(
            message="not live yet",
            scope="system",
            starts_at=timezone.now() + timezone.timedelta(days=7),
        )
        api_client.force_authenticate(user=staff)

        response = api_client.get(f"{URL}?include_inactive=true")

        assert response.status_code == 200
        assert scheduled.pk in _ids(response)


class TestIntendedSurfaceStillWorks:
    def test_caller_sees_system_own_user_and_own_workspace_banners(self, api_client, user_factory, workspace_factory):
        caller = user_factory()
        workspace = workspace_factory()
        _join(workspace, caller)
        system = _banner_model().objects.create(message="maintenance", scope="system")
        mine = _banner_model().objects.create(message="hello", scope="user", user=caller)
        ours = _banner_model().objects.create(message="team notice", scope="workspace", workspace=workspace)
        api_client.force_authenticate(user=caller)

        response = api_client.get(f"{URL}?workspace={workspace.id}")

        assert response.status_code == 200
        returned = _ids(response)
        assert {system.pk, mine.pk, ours.pk} <= returned

    def test_unknown_workspace_param_narrows_rather_than_errors(self, api_client, user_factory):
        """The frontend sends ``?seed=<id>``, a parameter this view never read.
        An unrecognised or foreign scope must degrade to fewer rows, not a 4xx.
        """
        caller = user_factory()
        system = _banner_model().objects.create(message="maintenance", scope="system")
        api_client.force_authenticate(user=caller)

        response = api_client.get(f"{URL}?seed={uuid.uuid4()}")

        assert response.status_code == 200
        assert system.pk in _ids(response)


class TestWriteVerbsStayStaffOnly:
    """Already correct on main. Pinned so a refactor cannot loosen it."""

    def test_anonymous_create_is_refused(self, api_client):
        before = _banner_model().objects.count()

        response = api_client.post(URL, {"message": "[QA] injected"}, format="json")

        assert response.status_code == 401
        assert _banner_model().objects.count() == before

    def test_ordinary_user_cannot_create(self, api_client, user_factory):
        api_client.force_authenticate(user=user_factory())
        before = _banner_model().objects.count()

        response = api_client.post(URL, {"message": "[QA] injected"}, format="json")

        assert response.status_code == 403
        assert _banner_model().objects.count() == before

    def test_ordinary_user_cannot_delete(self, api_client, user_factory):
        banner = _banner_model().objects.create(message="system notice", scope="system")
        api_client.force_authenticate(user=user_factory())

        response = api_client.delete(f"{URL}{banner.pk}/")

        assert response.status_code == 403
        assert _banner_model().objects.filter(pk=banner.pk).exists()
