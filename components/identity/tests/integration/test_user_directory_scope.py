"""There is no user directory on identity — and the one that remains is scoped.

Two endpoints used to answer "who exists on this installation":

* ``GET /identity/users/``   (``UserViewSet.list``)
* ``GET /identity/search/``  (``UserSearch``) and ``search/<query>/``

Both answered **200 with no credentials**, returning every user row in the
database — email, first/last name, username, and the workspaces each belongs
to. #414 shut them with ``IsAuthenticated`` + tenant scoping.

This module pins the resting state that followed. A caller inventory across
both repos found **nothing** using either route: the frontend's ``USERS_URL``
constant is defined and never imported, and its ``userSearch`` chain
dead-ends in the profile context with no consumer. An authenticated directory
that nothing calls buys no capability while keeping alive one of the two seams
that just leaked, so both are **removed** rather than merely gated. Person
lookup has one home — the membership context.

The invariants these tests pin:

* neither identity directory route serves a user list to anyone, at any
  privilege level, ever again — and the removal is asserted on the *body*,
  not only the status code;
* the object-scoped account routes that #414/#416 left behind still deny
  anonymous callers (removing ``list`` must not have loosened its neighbours);
* ``/membership/users/search/`` — the surviving canonical people seam — is
  authenticated and never returns a user from a workspace the caller is not a
  tenant of;
* the tenancy predicate behind it is **owns the workspace, or holds an ACTIVE
  ``WorkspaceMembership``** — the same rule ``WorkspaceQueryRepository
  .scope_to_user`` and ``user_is_active_workspace_member`` use. Owner counts
  even without a scaffolding membership row; nothing wider counts at all.

Tests create their own users; they never read deployed rows, and they assert
on the opaque ``username``/id values they generated rather than echoing
address-shaped PII around the suite.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


LIST_URL = "/identity/users/"
SEARCH_URL = "/identity/search/"
SEARCH_BY_QUERY_URL = "/identity/search/tenant/"
MEMBERSHIP_SEARCH_URL = "/membership/users/search/"

# A uuid that matches nothing. Probing authz with it proves the deny happens
# before any lookup, and touches no row.
ABSENT_ID = "00000000-0000-4000-8000-00000000dead"


def _make_user(email: str) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password="pass1234")
    UserProfile.objects.get_or_create(user=user)
    return user


def _make_workspace(owner: CustomUser, name: str, *, with_owner_membership: bool = True) -> Workspace:
    """A workspace, optionally WITHOUT the owner's scaffolding membership row.

    ``with_owner_membership=False`` reproduces the shape the codebase already
    knows exists — ``membership_query_repository`` carries an explicit
    "include the workspace owner even if they don't have an explicit
    WorkspaceMembership row (legacy data)" branch. The old identity predicate
    was membership-only and therefore disagreed with that on exactly this row.
    """
    workspace = Workspace.objects.create(workspace_name=name, workspace_owner=owner, status="active")
    if with_owner_membership:
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=owner,
            persona="admin",
            role=WorkspaceMembership.Role.OWNER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
    return workspace


def _add_member(workspace: Workspace, user: CustomUser, *, status=WorkspaceMembership.Status.ACTIVE) -> None:
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        persona="contributor",
        role=WorkspaceMembership.Role.MEMBER,
        status=status,
    )


def _body_text(response) -> str:
    """The whole response body as text, for 'no data leaked' assertions.

    Status codes are easy to get right by accident; this asserts the payload
    itself carries no identifier we planted.
    """
    return response.content.decode("utf-8", errors="replace")


def _member_search_ids(response) -> set[str]:
    return {row["id"] for row in response.data["results"]}


# ── two tenants that must never see each other ──────────────────────────────


@pytest.fixture
def two_tenants():
    """Two disjoint workspaces, each with an owner and a member."""
    alpha_owner = _make_user("alpha-owner@tenant-a.test")
    alpha_member = _make_user("alpha-member@tenant-a.test")
    alpha = _make_workspace(alpha_owner, "Tenant Alpha")
    _add_member(alpha, alpha_member)

    beta_owner = _make_user("beta-owner@tenant-b.test")
    beta_member = _make_user("beta-member@tenant-b.test")
    beta = _make_workspace(beta_owner, "Tenant Beta")
    _add_member(beta, beta_member)

    return {
        "alpha": alpha,
        "alpha_owner": alpha_owner,
        "alpha_member": alpha_member,
        "beta": beta,
        "beta_owner": beta_owner,
        "beta_member": beta_member,
    }


# ── the identity directory routes are GONE ──────────────────────────────────
#
# Anonymous callers still see the deployed 401 (authentication runs before
# handler lookup), so nothing an unauthenticated attacker can observe changed.
# Past that gate there is simply nothing to serve: 405 (no handler for the
# verb) on the collection, 404 (no route) on search. Both are strictly stronger
# than a permission check, because there is no code path left that could
# regress into serving rows if a permission class is edited later.
#
# Every assertion below pins the status AND the body — a status code is easy to
# get right by accident.


def test_anonymous_user_list_serves_nothing(api_client, two_tenants):
    """Still 401, exactly as deployed — the removal did not change this answer.

    ``get_permissions`` now defaults to ``IsAuthenticated`` for any action it
    does not recognise, and a GET on the collection route maps to no action at
    all now that ``list`` is gone. DRF authenticates in ``initial()`` before it
    looks for a handler, so an anonymous caller is turned away at the door and
    never learns the route lost its handler.
    """
    response = api_client.get(LIST_URL)

    assert response.status_code == 401, (
        f"unauthenticated GET {LIST_URL} returned {response.status_code}; "
        "anyone who can reach the API can dump every tenant's users"
    )
    assert two_tenants["alpha_owner"].username not in _body_text(response)


def test_authenticated_user_list_serves_nothing(api_client, two_tenants):
    """The narrowing this change makes: a signed-in caller gets no directory either.

    Before this change the same request returned 200 with the caller's own
    tenant's users. Nothing consumed that, so it is gone.
    """
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(LIST_URL)

    assert response.status_code == 405, (
        f"GET {LIST_URL} returned {response.status_code}; the identity user directory is supposed to be removed"
    )
    body = _body_text(response)
    assert two_tenants["alpha_member"].username not in body
    assert two_tenants["beta_member"].username not in body, "cross-tenant leak survived the removal"


def test_staff_user_list_serves_nothing(api_client, two_tenants):
    """Removed for everyone — staff included. Staff had the widest view of all."""
    staff = _make_user("staff@autosec.test")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    api_client.force_authenticate(user=staff)

    response = api_client.get(LIST_URL, {"page_size": 100})

    assert response.status_code == 405
    body = _body_text(response)
    assert two_tenants["alpha_owner"].username not in body
    assert two_tenants["beta_owner"].username not in body


@pytest.mark.parametrize("url", [SEARCH_URL, SEARCH_BY_QUERY_URL])
def test_identity_search_routes_are_gone(api_client, two_tenants, url):
    """Both spellings of the identity search route, unauthenticated."""
    response = api_client.get(url, {"query": "tenant"})

    assert response.status_code == 404, (
        f"GET {url} returned {response.status_code}; the identity user-search route is supposed to be removed"
    )
    assert two_tenants["beta_owner"].username not in _body_text(response)


@pytest.mark.parametrize("url", [SEARCH_URL, SEARCH_BY_QUERY_URL])
def test_identity_search_routes_are_gone_for_authenticated_callers(api_client, two_tenants, url):
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(url, {"query": "tenant"})

    assert response.status_code == 404, f"GET {url} returned {response.status_code}, expected the route to be absent"
    assert two_tenants["alpha_member"].username not in _body_text(response)


def test_identity_search_route_cannot_create_accounts(api_client):
    """``UserSearch`` was a ``ListCreateAPIView`` — POST ran ``UserSerializer.create``.

    #414 removed the write verb; this change removes the route. Pinned because
    "a search endpoint that mints accounts" is the exact defect class that
    keeps recurring on this viewset.
    """
    before = CustomUser.objects.count()

    response = api_client.post(
        SEARCH_URL,
        {"username": "smuggled", "email": "smuggled@tenant-x.test", "password": "pass1234"},
        format="json",
    )

    assert response.status_code == 404
    assert CustomUser.objects.count() == before, "an account was created through the removed search endpoint"


# ── the object-scoped account routes must NOT have loosened ─────────────────
#
# Removing an action from a viewset rewrites its router mapping, so the
# neighbouring verbs are re-asserted here rather than assumed. These pin the
# denies #414/#416 deployed.


def test_object_scoped_user_read_still_denies_anonymous(api_client, two_tenants):
    response = api_client.get(f"{LIST_URL}{two_tenants['alpha_owner'].id}/")

    assert response.status_code in (401, 403), (
        f"GET {LIST_URL}<id>/ returned {response.status_code}; unauthenticated PII read is back"
    )
    assert two_tenants["alpha_owner"].username not in _body_text(response)


def test_object_scoped_user_delete_still_denies_anonymous(api_client, two_tenants):
    before = CustomUser.objects.count()

    response = api_client.delete(f"{LIST_URL}{two_tenants['alpha_owner'].id}/")

    assert response.status_code in (401, 403), (
        f"DELETE {LIST_URL}<id>/ returned {response.status_code}; unauthenticated account deletion is back"
    )
    assert CustomUser.objects.count() == before


def test_object_scoped_user_update_still_denies_anonymous(api_client, two_tenants):
    response = api_client.patch(
        f"{LIST_URL}{two_tenants['alpha_owner'].id}/",
        {"first_name": "takenover"},
        format="json",
    )

    assert response.status_code in (401, 403), (
        f"PATCH {LIST_URL}<id>/ returned {response.status_code}; unauthenticated account takeover is back"
    )
    two_tenants["alpha_owner"].refresh_from_db()
    assert two_tenants["alpha_owner"].first_name != "takenover"


@pytest.mark.parametrize("method,payload", [("get", None), ("patch", {"first_name": "x"}), ("delete", None)])
def test_object_scoped_routes_are_not_an_existence_oracle(api_client, two_tenants, method, payload):
    """An anonymous caller must not be able to tell a real account from a fake one.

    ``IsLoggedInUserOrAdmin`` implements only ``has_object_permission``, which
    DRF evaluates *after* ``get_object()``. Without an ``IsAuthenticated``
    alongside it, an anonymous GET/PATCH of an existing id was denied while the
    same request for an absent id 404'd — a credential-free user-enumeration
    oracle on the viewset #414 de-enumerated. ``destroy`` already carried the
    explicit authentication gate; ``retrieve``/``update`` did not.
    """
    real = api_client.generic(method.upper(), f"{LIST_URL}{two_tenants['alpha_owner'].id}/")
    absent = api_client.generic(method.upper(), f"{LIST_URL}{ABSENT_ID}/")

    assert real.status_code == absent.status_code, (
        f"{method.upper()} {LIST_URL}<id>/ answered {real.status_code} for a real account and "
        f"{absent.status_code} for one that does not exist — that difference enumerates users"
    )
    assert real.status_code == 401


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/workspaces/"),
        ("patch", f"/workspaces/{ABSENT_ID}/"),
        ("delete", f"/workspaces/{ABSENT_ID}/"),
    ],
)
def test_workspace_surface_still_denies_anonymous(api_client, method, url):
    """The workspace denies landed alongside this work (#419) — re-pinned here.

    They share the tenancy predicate this change converges on, so a regression
    in one is a regression in the other. A non-existent uuid proves the deny
    fires before any lookup and touches no row.
    """
    response = getattr(api_client, method)(url, {} if method != "get" else None, format="json")

    assert response.status_code in (401, 403), (
        f"{method.upper()} {url} returned {response.status_code}, expected a deny"
    )


# ── the surviving canonical seam: /membership/users/search/ ─────────────────


def test_membership_user_search_denies_anonymous(api_client, two_tenants):
    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "tenant"})

    assert response.status_code in (401, 403), (
        f"unauthenticated GET {MEMBERSHIP_SEARCH_URL} returned {response.status_code}; "
        "the people typeahead is an account-existence oracle"
    )
    assert two_tenants["beta_owner"].username not in _body_text(response)


def test_membership_user_search_does_not_leak_another_tenant(api_client, two_tenants):
    """The tenant boundary, asserted directly: authenticate as A, ask for B.

    Single-DB + application-enforced isolation means a missing filter here IS
    the leak — there is no database boundary behind it.
    """
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "beta-"})

    assert response.status_code == 200
    assert response.data["results"] == [], "cross-tenant leak: another workspace's people came back"
    body = _body_text(response)
    assert two_tenants["beta_owner"].username not in body
    assert two_tenants["beta_member"].username not in body


def test_membership_user_search_still_finds_own_co_members(api_client, two_tenants):
    """Scoping, not amputation — the people-picker keeps working inside a tenant."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "alpha-member"})

    assert response.status_code == 200
    assert str(two_tenants["alpha_member"].id) in _member_search_ids(response)


def test_user_in_no_workspace_finds_nobody(api_client):
    """A user who is a tenant of nothing shares a workspace with nobody."""
    loner = _make_user("loner@tenant-c.test")
    other = _make_user("other@tenant-d.test")
    _make_workspace(other, "Somebody Else's Org")
    api_client.force_authenticate(user=loner)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "other"})

    assert response.status_code == 200
    assert response.data["results"] == []


# ── the tenancy predicate: owner OR active membership, nothing wider ────────


def test_owner_without_membership_row_can_see_their_own_members(api_client):
    """The convergence this change makes.

    The identity predicate was ACTIVE-membership-only, so an owner whose
    scaffolding ``WorkspaceMembership`` row is missing was a tenant of nothing
    — invisible to their own colleagues and unable to see them. Ownership is
    the workspace's own column; the membership row is derived scaffolding.
    ``WorkspaceQueryRepository.scope_to_user`` and
    ``user_is_active_workspace_member`` already count owners. This makes the
    third seam agree.
    """
    owner = _make_user("legacy-owner@tenant-e.test")
    member = _make_user("legacy-member@tenant-e.test")
    workspace = _make_workspace(owner, "Legacy Org", with_owner_membership=False)
    _add_member(workspace, member)
    api_client.force_authenticate(user=owner)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "legacy-member"})

    assert response.status_code == 200
    assert str(member.id) in _member_search_ids(response), (
        "an owner could not see a member of the workspace they own — the predicate is drawn "
        "from the membership table instead of from ownership"
    )


def test_member_can_see_an_owner_without_a_membership_row(api_client):
    """The same gap from the other side: the owner must not be invisible."""
    owner = _make_user("legacy-owner2@tenant-f.test")
    member = _make_user("legacy-member2@tenant-f.test")
    workspace = _make_workspace(owner, "Legacy Org Two", with_owner_membership=False)
    _add_member(workspace, member)
    api_client.force_authenticate(user=member)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "legacy-owner2"})

    assert response.status_code == 200
    assert str(owner.id) in _member_search_ids(response), "a member could not see the owner of their own workspace"


def test_owner_arm_does_not_cross_the_tenant_boundary(api_client, two_tenants):
    """Adding the owner arm must widen visibility WITHIN a tenant, never across."""
    owner = _make_user("solo-owner@tenant-g.test")
    _make_workspace(owner, "Solo Org", with_owner_membership=False)
    api_client.force_authenticate(user=owner)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "alpha-"})

    assert response.status_code == 200
    assert response.data["results"] == [], "the owner arm leaked another tenant's people"


@pytest.mark.parametrize(
    "membership_status",
    [WorkspaceMembership.Status.INVITED, WorkspaceMembership.Status.SUSPENDED],
)
def test_non_active_membership_grants_no_visibility(api_client, membership_status):
    """Pending and revoked tenancies were explicitly rejected as too permissive.

    Widening past ACTIVE would mean an invite that was never accepted — or a
    membership deliberately suspended — still reads the tenant's directory.
    """
    owner = _make_user("active-owner@tenant-h.test")
    outsider = _make_user("not-yet@tenant-h.test")
    workspace = _make_workspace(owner, "Gated Org")
    _add_member(workspace, outsider, status=membership_status)
    api_client.force_authenticate(user=outsider)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "active-owner"})

    assert response.status_code == 200
    assert response.data["results"] == [], (
        f"a {membership_status} membership granted directory visibility; only ACTIVE may"
    )


def test_team_membership_alone_grants_no_visibility(api_client):
    """We did NOT adopt the roster's wider predicate, and this pins that.

    ``/membership/members/`` walks ``Team.members`` as well as
    ``WorkspaceMembership`` — but it is object-scoped to a single workspace
    the caller has *already* been authorized on. This seam answers the prior
    question of which tenants a caller may see people from at all, so a stale
    team row must not re-open it.
    """
    owner = _make_user("team-owner@tenant-i.test")
    stale = _make_user("stale-team-user@tenant-i.test")
    workspace = _make_workspace(owner, "Team Org")
    team = Team.objects.create(workspace=workspace, title="Blue Team", created_by=owner)
    team.members.add(stale)
    api_client.force_authenticate(user=stale)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "team-owner"})

    assert response.status_code == 200
    assert response.data["results"] == [], (
        "a Team.members row with no ACTIVE WorkspaceMembership granted directory visibility"
    )


def test_staff_keep_system_wide_visibility(api_client, two_tenants):
    """Platform administration is unchanged — staff still see across tenants."""
    staff = _make_user("staff-search@autosec.test")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    api_client.force_authenticate(user=staff)

    response = api_client.get(MEMBERSHIP_SEARCH_URL, {"q": "owner@tenant-"})

    assert response.status_code == 200
    returned = _member_search_ids(response)
    assert str(two_tenants["alpha_owner"].id) in returned
    assert str(two_tenants["beta_owner"].id) in returned
