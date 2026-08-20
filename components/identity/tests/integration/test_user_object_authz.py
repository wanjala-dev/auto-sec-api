"""Per-verb authorization for the object-scoped identity endpoints.

Four legacy identity views were mapped to
``IsUnauthenticatedOrAdminOrStaff`` — a permission class *every* branch of
whose ``has_permission`` returns ``True`` and which defines no
``has_object_permission``. Nothing in the chain ever denied, so each view
answered with **no credentials at all**:

* ``PATCH /identity/edit/<uuid>/``    (``UserPatchView``)   — rewrote any
  user's ``email`` / ``username`` / ``first_name`` / ``last_name``: a
  one-request, unauthenticated **account-takeover** primitive (change the
  victim's email, then drive password-reset to an inbox you control).
* ``PATCH /identity/profile/<uuid>/`` (``ProfileEditView``) — rewrote any
  user's profile (name, bio, address, dob …) unauthenticated.
* ``GET /identity/detail/<id>/``      (``UserDetails``)     — returned any
  user's ``email`` / names / workspaces unauthenticated: a cross-tenant PII
  read and enumeration oracle.
* ``GET /identity/workspaces/<pk>/``  (``ListWorkspaces``)  — returned any
  user's workspace list unauthenticated.

autosec is single-database with application-enforced isolation, so there is
no database boundary behind these seams: the authorization check *is* the
tenant boundary. These are the same class of hole as the unauthenticated
``GET /identity/users/`` (#414) and ``DELETE /identity/users/<id>/`` (#402).

The invariants pinned here (mirroring ``UserViewSet``'s self-or-staff model):

* anonymous callers can never read or write another account or profile;
* an authenticated caller can never read or write a *different* user's
  account, profile, or workspace list — self-or-staff only;
* the caller keeps full access to their **own** account/profile/workspaces;
* staff keep administrative reach.

Tests create their own users; they never read or mutate deployed rows.
"""

from __future__ import annotations

import uuid

import pytest

from infrastructure.persistence.users.models import CustomUser, UserProfile

pytestmark = pytest.mark.django_db


def _make_user(email: str, **flags) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password="pass1234")
    UserProfile.objects.get_or_create(user=user)
    for k, v in flags.items():
        setattr(user, k, v)
    if flags:
        user.save(update_fields=list(flags))
    return user


@pytest.fixture
def victim() -> CustomUser:
    return _make_user("victim@tenant-a.test", first_name="Original")


@pytest.fixture
def attacker() -> CustomUser:
    # A fully separate account in no shared workspace with the victim.
    return _make_user("attacker@tenant-b.test")


def _edit_url(u: CustomUser) -> str:
    return f"/identity/edit/{u.id}/"


def _profile_url(u: CustomUser) -> str:
    return f"/identity/profile/{u.id}/"


def _detail_url(u: CustomUser) -> str:
    return f"/identity/detail/{u.id}/"


def _workspaces_url(u: CustomUser) -> str:
    return f"/identity/workspaces/{u.id}/"


# ── PATCH /identity/edit/<uuid>/  (account takeover) ────────────────────────


def test_anonymous_cannot_patch_account(api_client, victim):
    """No credentials must never rewrite an account's email/username."""
    response = api_client.patch(_edit_url(victim), {"first_name": "PWNED"}, format="json")

    assert response.status_code in (401, 403), (
        f"unauthenticated PATCH {_edit_url(victim)} returned {response.status_code}; "
        "anyone who can reach the API can take over any account"
    )
    victim.refresh_from_db()
    assert victim.first_name == "Original", "unauthenticated write reached the row"


def test_other_user_cannot_patch_account(api_client, victim, attacker):
    """A signed-in user must not rewrite a *different* account."""
    api_client.force_authenticate(user=attacker)

    response = api_client.patch(_edit_url(victim), {"email": "hijacked@evil.test"}, format="json")

    assert response.status_code in (403, 404), (
        f"cross-user PATCH {_edit_url(victim)} returned {response.status_code}; "
        "an authenticated user rewrote another account"
    )
    victim.refresh_from_db()
    assert victim.email == "victim@tenant-a.test", "cross-user write reached the row"


def test_self_can_patch_own_account(api_client, victim):
    """The owner keeps full access to their own account."""
    api_client.force_authenticate(user=victim)

    response = api_client.patch(_edit_url(victim), {"first_name": "Renamed"}, format="json")

    assert response.status_code == 200, f"self-edit returned {response.status_code}, expected 200"
    victim.refresh_from_db()
    assert victim.first_name == "Renamed"


# ── PATCH /identity/profile/<uuid>/ ─────────────────────────────────────────


def test_anonymous_cannot_patch_profile(api_client, victim):
    response = api_client.patch(_profile_url(victim), {"bio": "pwned"}, format="json")

    assert response.status_code in (401, 403), (
        f"unauthenticated PATCH {_profile_url(victim)} returned {response.status_code}"
    )


def test_other_user_cannot_patch_profile(api_client, victim, attacker):
    api_client.force_authenticate(user=attacker)

    response = api_client.patch(_profile_url(victim), {"bio": "pwned"}, format="json")

    assert response.status_code in (403, 404), (
        f"cross-user PATCH {_profile_url(victim)} returned {response.status_code}; "
        "an authenticated user rewrote another user's profile"
    )


def test_self_can_patch_own_profile(api_client, victim):
    api_client.force_authenticate(user=victim)

    response = api_client.patch(_profile_url(victim), {"bio": "mine"}, format="json")

    assert response.status_code == 200, f"self profile-edit returned {response.status_code}"


# ── GET /identity/detail/<id>/  (PII read) ──────────────────────────────────


def test_anonymous_cannot_read_user_detail(api_client, victim):
    """No credentials must never return another account's email/names."""
    response = api_client.get(_detail_url(victim))

    assert response.status_code in (401, 403), (
        f"unauthenticated GET {_detail_url(victim)} returned {response.status_code}; "
        "cross-tenant PII read and enumeration oracle"
    )


def test_other_user_cannot_read_user_detail(api_client, victim, attacker):
    api_client.force_authenticate(user=attacker)

    response = api_client.get(_detail_url(victim))

    assert response.status_code in (403, 404), (
        f"cross-user GET {_detail_url(victim)} returned {response.status_code}; "
        "an authenticated user read another account's detail"
    )


def test_self_can_read_own_detail(api_client, victim):
    api_client.force_authenticate(user=victim)

    response = api_client.get(_detail_url(victim))

    assert response.status_code == 200, f"self detail returned {response.status_code}"


# ── GET /identity/workspaces/<pk>/ ──────────────────────────────────────────


def test_anonymous_cannot_read_user_workspaces(api_client, victim):
    response = api_client.get(_workspaces_url(victim))

    assert response.status_code in (401, 403), (
        f"unauthenticated GET {_workspaces_url(victim)} returned {response.status_code}"
    )


def test_other_user_cannot_read_user_workspaces(api_client, victim, attacker):
    api_client.force_authenticate(user=attacker)

    response = api_client.get(_workspaces_url(victim))

    assert response.status_code in (403, 404), (
        f"cross-user GET {_workspaces_url(victim)} returned {response.status_code}; "
        "an authenticated user read another user's workspace list"
    )


def test_self_can_read_own_workspaces(api_client, victim):
    api_client.force_authenticate(user=victim)

    response = api_client.get(_workspaces_url(victim))

    assert response.status_code == 200, f"self workspaces returned {response.status_code}"


# ── staff retains administrative reach ──────────────────────────────────────


def test_staff_can_read_any_user_detail(api_client, victim):
    staff = _make_user("staff@autosec.test", is_staff=True)
    api_client.force_authenticate(user=staff)

    response = api_client.get(_detail_url(victim))

    assert response.status_code == 200, f"staff detail read returned {response.status_code}"


def test_nonexistent_user_denies_before_leaking_existence(api_client, attacker):
    """An unauthenticated probe for a random id must deny, not 404/500.

    A 404 here (row-missing) proves the request sailed past authz into the
    lookup; the deny must land *before* the object is resolved.
    """
    missing = uuid.uuid4()
    response = api_client.patch(f"/identity/edit/{missing}/", {"first_name": "x"}, format="json")

    assert response.status_code in (401, 403), (
        f"unauthenticated PATCH of a random id returned {response.status_code}; "
        "authz must deny before the object lookup"
    )
