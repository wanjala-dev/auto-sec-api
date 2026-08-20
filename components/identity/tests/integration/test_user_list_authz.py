"""Authorization + tenant scoping for the identity user-listing endpoints.

``GET /identity/users/`` (``UserViewSet.list``) and ``GET /identity/search/``
(``UserSearch``) both answered **200 with no credentials**, returning every
user row in the database — email, first/last name, username, and the
workspaces each belongs to.

autosec is single-database with application-enforced tenant isolation, so
there is no database boundary behind these reads to catch a missing filter:
the queryset scoping *is* the tenant boundary. An unscoped list is therefore
a cross-tenant PII dump as well as user enumeration — and enumeration was
step 1 of the repro for the unauthenticated-DELETE hole fixed in #402
(you need a victim id before you can delete it).

The invariants these tests pin:

* anonymous callers can never list or search users;
* an authenticated caller never sees a user from a workspace they are not an
  active member of — this is the tenant boundary, asserted directly;
* co-members of a shared workspace stay visible, so the people surfaces keep
  working (this is a scoping fix, not a capability removal);
* staff/superuser keep system-wide visibility;
* the search endpoint handles a missing or blank query cleanly instead of
  raising, and never degrades into "match everything";
* the search route is read-only — it must not double as an unauthenticated
  account-creation endpoint.

Tests create their own users; they never read deployed rows.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = pytest.mark.django_db


LIST_URL = "/identity/users/"
SEARCH_URL = "/identity/search/"


def _make_user(email: str) -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password="pass1234")
    UserProfile.objects.get_or_create(user=user)
    return user


def _make_workspace(owner: CustomUser, name: str) -> Workspace:
    workspace = Workspace.objects.create(workspace_name=name, workspace_owner=owner, status="active")
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        persona="admin",
        role=WorkspaceMembership.Role.OWNER,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    return workspace


def _add_member(workspace: Workspace, user: CustomUser) -> None:
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        persona="contributor",
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )


def _usernames(response) -> set[str]:
    """Identifiers returned by a list/search response.

    Asserts on the opaque ``username`` we generated in-test rather than
    echoing address-shaped PII around the suite.
    """
    payload = response.data
    if isinstance(payload, dict):
        rows = payload.get("results", payload.get("data", []))
    else:
        rows = payload
    return {row["username"] for row in rows}


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
        "alpha_owner": alpha_owner,
        "alpha_member": alpha_member,
        "beta_owner": beta_owner,
        "beta_member": beta_member,
    }


# ── GET /identity/users/ ────────────────────────────────────────────────────


def test_anonymous_user_list_is_denied(api_client, two_tenants):
    """No credentials at all must never return a user directory."""
    response = api_client.get(LIST_URL)

    assert response.status_code in (401, 403), (
        f"unauthenticated GET {LIST_URL} returned {response.status_code}; "
        "anyone who can reach the API can dump every tenant's users"
    )


def test_user_list_does_not_leak_another_tenant(api_client, two_tenants):
    """The tenant boundary: a caller must not see users from a workspace they are not in.

    Single-DB + application-enforced isolation means a missing filter here IS
    the leak — there is no database boundary behind it.
    """
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(LIST_URL)

    assert response.status_code == 200
    returned = _usernames(response)
    assert two_tenants["beta_owner"].username not in returned, "cross-tenant leak: saw another workspace's owner"
    assert two_tenants["beta_member"].username not in returned, "cross-tenant leak: saw another workspace's member"


def test_user_list_still_shows_shared_workspace_members(api_client, two_tenants):
    """Co-members stay visible — this is a scoping fix, not a capability removal."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(LIST_URL)

    assert response.status_code == 200
    returned = _usernames(response)
    assert two_tenants["alpha_owner"].username in returned, "caller lost sight of themselves"
    assert two_tenants["alpha_member"].username in returned, "caller lost sight of their own workspace co-member"


def test_user_without_membership_sees_only_self(api_client):
    """A user in no workspace shares a workspace with nobody — so only themselves."""
    loner = _make_user("loner@tenant-c.test")
    other = _make_user("other@tenant-d.test")
    _make_workspace(other, "Somebody Else's Org")
    api_client.force_authenticate(user=loner)

    response = api_client.get(LIST_URL)

    assert response.status_code == 200
    assert _usernames(response) == {loner.username}


def test_staff_sees_every_user(api_client, two_tenants):
    """Staff administration keeps system-wide visibility."""
    staff = _make_user("staff@autosec.test")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    api_client.force_authenticate(user=staff)

    response = api_client.get(LIST_URL, {"page_size": 100})

    assert response.status_code == 200
    returned = _usernames(response)
    assert two_tenants["alpha_owner"].username in returned
    assert two_tenants["beta_owner"].username in returned


# ── GET /identity/search/ ───────────────────────────────────────────────────


def test_anonymous_search_is_denied(api_client, two_tenants):
    """Search must not be an anonymous user-enumeration oracle."""
    response = api_client.get(SEARCH_URL, {"query": "tenant"})

    assert response.status_code in (401, 403), (
        f"unauthenticated GET {SEARCH_URL} returned {response.status_code}; anyone can probe which accounts exist"
    )


def test_anonymous_search_without_query_does_not_error(api_client):
    """The 500 was itself the tell: unauthenticated input reached the ORM."""
    response = api_client.get(SEARCH_URL, {"q": "a"})

    assert response.status_code in (401, 403), (
        f"GET {SEARCH_URL}?q=a returned {response.status_code}; an unauthenticated "
        "500 leaks stack shape and means the query ran before any authz check"
    )


def test_search_with_missing_query_returns_empty_not_500(api_client, two_tenants):
    """A missing ``query`` used to reach ``icontains=None`` and raise ValueError."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(SEARCH_URL)

    assert response.status_code == 200, f"missing query returned {response.status_code}, expected a clean 200"
    assert _usernames(response) == set(), "a missing query must not fall through to 'match everything'"


def test_search_with_blank_query_does_not_dump_the_directory(api_client, two_tenants):
    """``icontains=''`` matches every row — a blank query must not become a dump."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(SEARCH_URL, {"query": "   "})

    assert response.status_code == 200
    assert _usernames(response) == set()


def test_search_does_not_leak_another_tenant(api_client, two_tenants):
    """Same tenant boundary as the list — a match outside the caller's workspaces is a leak."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(SEARCH_URL, {"query": "beta-"})

    assert response.status_code == 200
    returned = _usernames(response)
    assert two_tenants["beta_owner"].username not in returned, "cross-tenant leak via search"
    assert two_tenants["beta_member"].username not in returned, "cross-tenant leak via search"


def test_search_finds_shared_workspace_members(api_client, two_tenants):
    """Search keeps working inside the caller's own workspaces."""
    api_client.force_authenticate(user=two_tenants["alpha_owner"])

    response = api_client.get(SEARCH_URL, {"query": "alpha-member"})

    assert response.status_code == 200
    assert two_tenants["alpha_member"].username in _usernames(response)


def test_search_route_cannot_create_accounts(api_client):
    """``UserSearch`` was a ``ListCreateAPIView`` — POST ran ``UserSerializer.create``.

    Registration has its own gated endpoints; a search route must never be a
    second, unauthenticated way to mint accounts.
    """
    before = CustomUser.objects.count()

    response = api_client.post(
        SEARCH_URL,
        {"username": "smuggled", "email": "smuggled@tenant-x.test", "password": "pass1234"},
        format="json",
    )

    assert response.status_code in (401, 403, 405), (
        f"POST {SEARCH_URL} returned {response.status_code}; the search route accepts writes"
    )
    assert CustomUser.objects.count() == before, "an account was created through the search endpoint"
