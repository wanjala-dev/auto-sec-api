"""Tenant isolation for the feature-flag read endpoints.

autosec is single-DB with application-enforced isolation, so a
workspace-scoped read that never checks membership IS a cross-tenant leak —
there is no database boundary behind it (CLAUDE.md, ADR 0028).

``/feature-flags/`` and ``/feature-flags/<key>/`` both accept a caller-supplied
``workspace_id``. Evaluated flags are a workspace's product configuration:
which scanners and capabilities are on, whether it is running on sample data,
whether the AI kill switch is tripped. That must never be readable by someone
outside the workspace, and the endpoint must not become a per-workspace oracle
that differentiates a foreign workspace from a nonexistent one.
"""

import uuid

import pytest
from django.urls import reverse

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]

FLAG_KEY = "demo.tenant_scoped"


@pytest.fixture
def foreign_workspace_with_flag_on(workspace_factory, user_factory):
    """A workspace the caller has nothing to do with, whose flag is ON.

    The flag is OFF by default, so a leaked ``True`` can only have come from
    this workspace's own WORKSPACE-scoped rule — it cannot be a default.
    """
    flag = FeatureFlag.objects.create(key=FLAG_KEY, default_enabled=False)
    workspace = workspace_factory(owner=user_factory())
    FeatureFlagRule.objects.create(
        flag=flag,
        scope=FeatureFlagRule.Scope.WORKSPACE,
        workspace=workspace,
        enabled=True,
    )
    return workspace


def _assert_no_leak(response):
    """A denied read must be a denial, not a differently-shaped answer."""
    assert response.status_code == 403, response.data
    assert FLAG_KEY not in str(response.data)


def test_flag_map_denies_a_foreign_workspace(api_client, user_factory, foreign_workspace_with_flag_on):
    outsider = user_factory()
    api_client.force_authenticate(user=outsider)

    response = api_client.get(f"{reverse('feature-flags')}?workspace_id={foreign_workspace_with_flag_on.id}")

    _assert_no_leak(response)


def test_flag_map_denies_a_foreign_workspace_via_the_workspace_alias(
    api_client, user_factory, foreign_workspace_with_flag_on
):
    """``?workspace=`` is the second accepted spelling — it must not be a bypass."""
    outsider = user_factory()
    api_client.force_authenticate(user=outsider)

    response = api_client.get(f"{reverse('feature-flags')}?workspace={foreign_workspace_with_flag_on.id}")

    _assert_no_leak(response)


def test_single_flag_denies_a_foreign_workspace(api_client, user_factory, foreign_workspace_with_flag_on):
    """The single-flag endpoint is the sharper oracle: one bit per query."""
    outsider = user_factory()
    api_client.force_authenticate(user=outsider)

    url = reverse("feature-flag", kwargs={"key": FLAG_KEY})
    response = api_client.get(f"{url}?workspace_id={foreign_workspace_with_flag_on.id}")

    assert response.status_code == 403, response.data
    assert "enabled" not in response.data


def test_a_nonexistent_workspace_is_denied_identically_to_a_foreign_one(
    api_client, user_factory, foreign_workspace_with_flag_on
):
    """No existence oracle: "not yours" and "not real" must be indistinguishable."""
    outsider = user_factory()
    api_client.force_authenticate(user=outsider)

    foreign = api_client.get(f"{reverse('feature-flags')}?workspace_id={foreign_workspace_with_flag_on.id}")
    nonexistent = api_client.get(f"{reverse('feature-flags')}?workspace_id={uuid.uuid4()}")

    assert nonexistent.status_code == foreign.status_code == 403
    assert str(nonexistent.data) == str(foreign.data)


def test_a_malformed_workspace_id_is_denied_not_a_server_error(api_client, user_factory):
    """A non-UUID must not reach the ORM (UUIDField raises → DRF renders 500)."""
    api_client.force_authenticate(user=user_factory())

    response = api_client.get(f"{reverse('feature-flags')}?workspace_id=not-a-uuid")

    assert response.status_code == 403, response.data


def test_an_active_member_still_reads_their_own_workspace(api_client, user_factory, workspace_factory):
    """The fix must gate strangers, not members — membership, not just ownership."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    workspace = workspace_factory(owner=user_factory())
    member = user_factory()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    FeatureFlag.objects.create(key=FLAG_KEY, default_enabled=True)

    api_client.force_authenticate(user=member)
    response = api_client.get(f"{reverse('feature-flags')}?workspace_id={workspace.id}")

    assert response.status_code == 200, response.data
    assert response.data["flags"][FLAG_KEY] is True


def test_an_invited_but_not_yet_active_member_is_denied(api_client, user_factory, foreign_workspace_with_flag_on):
    """An outstanding invite is not access."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    invitee = user_factory()
    WorkspaceMembership.objects.create(
        workspace=foreign_workspace_with_flag_on,
        user=invitee,
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.INVITED,
    )

    api_client.force_authenticate(user=invitee)
    response = api_client.get(f"{reverse('feature-flags')}?workspace_id={foreign_workspace_with_flag_on.id}")

    _assert_no_leak(response)


def test_the_bootstrap_call_without_a_workspace_id_still_works(api_client, user_factory):
    """The frontend bootstraps flags before a workspace is chosen.

    Gating on an *absent* workspace_id would 403 every first-run session, so
    the no-workspace path must stay open — it can only ever resolve to the
    caller's own active workspace.
    """
    FeatureFlag.objects.create(key=FLAG_KEY, default_enabled=True)

    api_client.force_authenticate(user=user_factory())
    response = api_client.get(reverse("feature-flags"))

    assert response.status_code == 200, response.data
    assert response.data["flags"][FLAG_KEY] is True
