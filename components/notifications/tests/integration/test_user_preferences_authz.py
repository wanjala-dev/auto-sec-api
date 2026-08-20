"""Authorization for the user notification-preference surface.

Found by the QA sweep on the live cluster, 2026-08-19, and reproduced against
the deployed api: ``GET http://autosec.local/userpreferences/`` returned **200
with one row per distinct user** — every account's notification preferences,
cross-tenant, with **no Authorization header at all**. The sibling detail route
returned a **500** unauthenticated, which is the same defect wearing a
different hat: the query ran before anything asked who was calling.

``UserPreferenceView`` (mounted at BOTH ``/userpreferences/`` and
``/notifications/userpreferences/``) was gated by
``components.workspace.api.workspace_permissions.IsUnauthenticatedOrAdminOrStaff``::

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated

Both branches are the bug, and the view had no object check behind either:

* **Safe methods returned ``True`` for anyone.** ``GET`` with no ``uuid``
  called ``UserPreference.objects.all()`` — an unauthenticated dump of every
  user on the pooled console. ``GET`` with a ``uuid`` read any single user's
  row. Registration is open, so the audience for both was "the internet".
* **Unsafe methods needed only "some account is logged in".** The ``uuid`` in
  the URL is a **user id**, and nothing compared it to the caller — so any
  authenticated user could ``PATCH`` another user's preferences (flipping
  ``notifications_enabled`` off is a silent, targeted denial of every security
  alert autosec sends them) or ``DELETE`` the row outright. ``UserPreference``
  is a plain ``models.Model``: that delete is a real row removal, not a
  tombstone.
* ``POST`` took a writable ``user`` field, so a logged-in account could plant
  a preference row for somebody else entirely.

The unauthenticated 500 on the detail route deserves its own note. The handler
reached ``CustomUser.objects.get(id=uuid)`` before any authorization ran, so an
anonymous caller could tell a **real user id from a fake one by the shape of
the crash** — a user-enumeration oracle on top of the leak. The fix authorizes
against the caller's own id *before* touching the database, so the deny costs
zero queries and leaks no existence signal.

The policy this module pins: **a user may read and write only their own
preferences**; staff/superusers may act on anyone, matching
``IsLoggedInUserOrAdmin`` as already used by ``UserViewSet`` and by the
identity views fixed in #416.

Every denial below asserts the EFFECT (the victim's row still exists, its
fields are unchanged) as well as the status code, so a later change to which
code is returned can never quietly turn a deny into an allow. Assertions are on
counts and field names only — this endpoint's whole problem is that it serves
PII, and a test transcript is not a good place for it.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.notifications.userpreferences.models import UserPreference

pytestmark = [pytest.mark.django_db]


# Both mount points share one view; every rule has to hold on both.
ROOT_MOUNT = "/userpreferences"
NOTIFICATIONS_MOUNT = "/notifications/userpreferences"
MOUNTS = (ROOT_MOUNT, NOTIFICATIONS_MOUNT)

# A caller who is denied before any lookup must be denied for an id that does
# not exist either — that is what proves the gate runs first.
ABSENT_USER_ID = "11111111-2222-3333-4444-555555555555"


def _staff(user_factory) -> object:
    """A staff account. ``create_user`` rejects ``is_staff``, so set it after."""
    user = user_factory()
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


def _prefs(user, **fields) -> UserPreference:
    """Set a user's preference row.

    A signal bridge already mints one when the account is created, so tests
    must never ``objects.create()`` here — the OneToOne would raise.
    """
    preference, _ = UserPreference.objects.update_or_create(user=user, defaults=fields)
    return preference


def _detail(mount: str, user_id) -> str:
    return f"{mount}/{user_id}/"


def _list(mount: str) -> str:
    return f"{mount}/"


class TestAnonymousCallersGetNothing:
    """The reported defect: no Authorization header, 200, everybody's rows."""

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_anonymous_list_is_401_and_returns_no_rows(self, api_client, user_factory, mount):
        for _ in range(3):
            _prefs(user_factory())

        response = api_client.get(_list(mount))

        assert response.status_code == 401, response.status_code
        # The leak was the body, not the code — make sure nothing rode along.
        body = response.content.decode()
        assert "darkmode" not in body
        assert "notifications_enabled" not in body

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_anonymous_detail_is_401_not_500(self, api_client, user_factory, mount):
        """The live route answered 500, which means the query beat the gate."""
        victim = user_factory()
        _prefs(victim)

        response = api_client.get(_detail(mount, victim.id))

        assert response.status_code == 401, response.status_code
        assert "darkmode" not in response.content.decode()

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_anonymous_detail_for_absent_id_is_401_not_500(self, api_client, mount):
        """No enumeration oracle: a fake id denies exactly like a real one."""
        response = api_client.get(_detail(mount, ABSENT_USER_ID))

        assert response.status_code == 401, response.status_code

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_anonymous_patch_is_401_and_changes_nothing(self, api_client, user_factory, mount):
        victim = user_factory()
        _prefs(victim, notifications_enabled=True)

        response = api_client.patch(
            _detail(mount, victim.id),
            {"notifications_enabled": False},
            format="json",
        )

        assert response.status_code == 401, response.status_code
        assert UserPreference.objects.get(user=victim).notifications_enabled is True

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_anonymous_delete_is_401_and_the_row_survives(self, api_client, user_factory, mount):
        victim = user_factory()
        _prefs(victim)

        response = api_client.delete(_detail(mount, victim.id))

        assert response.status_code == 401, response.status_code
        assert UserPreference.objects.filter(user=victim).exists()


class TestOneUserCannotTouchAnother:
    """Logged in is not the same as authorized. The uuid is a *user* id."""

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_peer_cannot_read_another_users_preferences(self, api_client, user_factory, mount):
        attacker, victim = user_factory(), user_factory()
        _prefs(victim)

        api_client.force_authenticate(user=attacker)
        response = api_client.get(_detail(mount, victim.id))

        assert response.status_code == 403, response.status_code
        assert "darkmode" not in response.content.decode()

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_peer_cannot_patch_another_users_preferences(self, api_client, user_factory, mount):
        attacker, victim = user_factory(), user_factory()
        _prefs(victim, notifications_enabled=True, email_notifications=True)

        api_client.force_authenticate(user=attacker)
        response = api_client.patch(
            _detail(mount, victim.id),
            {"notifications_enabled": False, "email_notifications": False},
            format="json",
        )

        assert response.status_code == 403, response.status_code
        preference = UserPreference.objects.get(user=victim)
        assert preference.notifications_enabled is True
        assert preference.email_notifications is True

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_peer_cannot_delete_another_users_preferences(self, api_client, user_factory, mount):
        attacker, victim = user_factory(), user_factory()
        _prefs(victim)

        api_client.force_authenticate(user=attacker)
        response = api_client.delete(_detail(mount, victim.id))

        assert response.status_code == 403, response.status_code
        assert UserPreference.objects.filter(user=victim).exists()

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_peer_cannot_plant_a_row_for_another_user_via_post(self, api_client, user_factory, mount):
        """``user`` is a writable serializer field; it must not be caller-chosen."""
        attacker, victim = user_factory(), user_factory()
        # Drop the row the signal bridge mints, so a created one is unambiguous.
        UserPreference.objects.filter(user=victim).delete()

        api_client.force_authenticate(user=attacker)
        response = api_client.post(
            _list(mount),
            {"user": str(victim.id), "darkmode": "Light"},
            format="json",
        )

        assert response.status_code == 403, response.status_code
        assert not UserPreference.objects.filter(user=victim).exists()

    def test_peer_denial_costs_no_lookup_for_an_absent_id(self, api_client, user_factory):
        """Deny before the query — so a bogus id 403s rather than 500ing."""
        attacker = user_factory()

        api_client.force_authenticate(user=attacker)
        response = api_client.get(_detail(ROOT_MOUNT, ABSENT_USER_ID))

        assert response.status_code == 403, response.status_code

    def test_peer_denial_survives_a_malformed_id(self, api_client, user_factory):
        """A non-uuid used to reach the ORM and raise; it must just deny."""
        attacker = user_factory()

        api_client.force_authenticate(user=attacker)
        response = api_client.get(_detail(ROOT_MOUNT, "not-a-uuid"))

        assert response.status_code == 403, response.status_code


class TestTheListIsScopedNotGlobal:
    """``UserPreference.objects.all()`` is never the right answer for a member."""

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_member_list_returns_only_their_own_row(self, api_client, user_factory, mount):
        caller = user_factory()
        _prefs(caller)
        for _ in range(3):
            _prefs(user_factory())

        api_client.force_authenticate(user=caller)
        response = api_client.get(_list(mount))

        assert response.status_code == 200, response.status_code
        rows = response.json()["data"]
        assert len(rows) == 1
        assert rows[0]["user"] == str(caller.id)

    def test_staff_list_still_sees_every_row(self, api_client, user_factory):
        staff = _staff(user_factory)
        _prefs(staff)
        for _ in range(3):
            _prefs(user_factory())

        api_client.force_authenticate(user=staff)
        response = api_client.get(_list(ROOT_MOUNT))

        assert response.status_code == 200, response.status_code
        assert len(response.json()["data"]) == UserPreference.objects.count()


class TestStaffKeepTheirReach:
    """Self-or-staff, matching ``IsLoggedInUserOrAdmin`` on ``UserViewSet``."""

    def test_staff_may_read_another_users_preferences(self, api_client, user_factory):
        staff, other = _staff(user_factory), user_factory()
        _prefs(other)

        api_client.force_authenticate(user=staff)
        response = api_client.get(_detail(ROOT_MOUNT, other.id))

        assert response.status_code == 200, response.status_code
        assert response.json()["data"]["user"] == str(other.id)

    def test_staff_may_patch_another_users_preferences(self, api_client, user_factory):
        staff, other = _staff(user_factory), user_factory()
        _prefs(other, notifications_enabled=True)

        api_client.force_authenticate(user=staff)
        response = api_client.patch(
            _detail(ROOT_MOUNT, other.id),
            {"notifications_enabled": False},
            format="json",
        )

        assert response.status_code == 200, response.status_code
        assert UserPreference.objects.get(user=other).notifications_enabled is False

    def test_staff_reading_an_absent_user_gets_404_not_500(self, api_client, user_factory):
        staff = _staff(user_factory)

        api_client.force_authenticate(user=staff)
        response = api_client.get(_detail(ROOT_MOUNT, ABSENT_USER_ID))

        assert response.status_code == 404, response.status_code

    def test_staff_reading_a_malformed_id_gets_404_not_500(self, api_client, user_factory):
        staff = _staff(user_factory)

        api_client.force_authenticate(user=staff)
        response = api_client.get(_detail(ROOT_MOUNT, "not-a-uuid"))

        assert response.status_code == 404, response.status_code


class TestOwnersKeepTheWorkingSurface:
    """The frontend calls GET + PATCH on ``/userpreferences/<own id>/``."""

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_owner_can_read_their_own_preferences(self, api_client, user_factory, mount):
        caller = user_factory()
        _prefs(caller)

        api_client.force_authenticate(user=caller)
        response = api_client.get(_detail(mount, caller.id))

        assert response.status_code == 200, response.status_code
        assert response.json()["data"]["user"] == str(caller.id)

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_owner_read_creates_the_row_on_demand(self, api_client, user_factory, mount):
        """``get_or_create`` behaviour the frontend relies on for new accounts."""
        caller = user_factory()
        UserPreference.objects.filter(user=caller).delete()

        api_client.force_authenticate(user=caller)
        response = api_client.get(_detail(mount, caller.id))

        assert response.status_code == 200, response.status_code
        assert UserPreference.objects.filter(user=caller).exists()

    @pytest.mark.parametrize("mount", MOUNTS)
    def test_owner_can_patch_their_own_preferences(self, api_client, user_factory, mount):
        caller = user_factory()
        _prefs(caller, notifications_enabled=True)

        api_client.force_authenticate(user=caller)
        response = api_client.patch(
            _detail(mount, caller.id),
            {"notifications_enabled": False, "darkmode": "Light"},
            format="json",
        )

        assert response.status_code == 200, response.status_code
        preference = UserPreference.objects.get(user=caller)
        assert preference.notifications_enabled is False
        assert preference.darkmode == "Light"

    def test_owner_can_delete_their_own_preferences(self, api_client, user_factory):
        caller = user_factory()
        _prefs(caller)

        api_client.force_authenticate(user=caller)
        response = api_client.delete(_detail(ROOT_MOUNT, caller.id))

        assert response.status_code in (200, 204), response.status_code
        assert not UserPreference.objects.filter(user=caller).exists()

    def test_owner_post_without_a_user_field_targets_themselves(self, api_client, user_factory):
        caller = user_factory()
        UserPreference.objects.filter(user=caller).delete()

        api_client.force_authenticate(user=caller)
        response = api_client.post(_list(ROOT_MOUNT), {"darkmode": "Light"}, format="json")

        assert response.status_code == 200, response.status_code
        assert UserPreference.objects.filter(user=caller).exists()

    def test_uuidless_routes_resolve_to_the_caller(self, api_client, user_factory):
        """``PATCH /userpreferences/`` used to 400; it now edits your own row."""
        caller = user_factory()
        _prefs(caller, notifications_enabled=True)
        bystander = user_factory()
        _prefs(bystander, notifications_enabled=True)

        api_client.force_authenticate(user=caller)
        response = api_client.patch(_list(ROOT_MOUNT), {"notifications_enabled": False}, format="json")

        assert response.status_code == 200, response.status_code
        assert UserPreference.objects.get(user=caller).notifications_enabled is False
        assert UserPreference.objects.get(user=bystander).notifications_enabled is True
