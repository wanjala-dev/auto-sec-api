"""Authorization coverage for ``DELETE /identity/users/<id>/``.

``UserViewSet.destroy`` hard-deletes a ``CustomUser`` row. Because autosec is
single-database with application-enforced tenant isolation, an unguarded
destroy is a cross-tenant account-takedown primitive: any caller who can reach
the API can remove another tenant's workspace owner.

The account row is the root of every workspace membership, so these are the
invariants that must never regress:

* anonymous callers can never delete an account;
* an authenticated user can never delete somebody else's account;
* self-service and staff deletion keep working.
"""

import pytest
from django.urls import reverse

from infrastructure.persistence.users.models import CustomUser

pytestmark = pytest.mark.django_db


def _detail_url(user):
    return reverse("users-detail", kwargs={"pk": str(user.id)})


def test_anonymous_delete_is_rejected_and_account_survives(api_client, user_factory):
    """No credentials at all must never destroy an account."""
    victim = user_factory()

    response = api_client.delete(_detail_url(victim))

    assert response.status_code in (401, 403), (
        f"unauthenticated DELETE returned {response.status_code}; "
        "any caller who can reach the API can delete any account"
    )
    assert CustomUser.objects.filter(pk=victim.pk).exists(), "victim account was hard-deleted by an anonymous caller"


def test_authenticated_user_cannot_delete_another_account(api_client, user_factory):
    """A signed-in, non-staff user must not reach across to another account."""
    attacker = user_factory()
    victim = user_factory()
    api_client.force_authenticate(user=attacker)

    response = api_client.delete(_detail_url(victim))

    assert response.status_code == 403
    assert CustomUser.objects.filter(pk=victim.pk).exists(), "victim account was hard-deleted by an unrelated user"


def test_user_can_delete_own_account(api_client, user_factory):
    """Self-service deletion stays available — this fix is about authz, not capability."""
    user = user_factory()
    api_client.force_authenticate(user=user)

    response = api_client.delete(_detail_url(user))

    assert response.status_code == 204
    assert not CustomUser.objects.filter(pk=user.pk).exists()


def test_staff_can_delete_any_account(api_client, user_factory):
    """Staff administration of accounts stays available."""
    staff = user_factory()
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    victim = user_factory()
    api_client.force_authenticate(user=staff)

    response = api_client.delete(_detail_url(victim))

    assert response.status_code == 204
    assert not CustomUser.objects.filter(pk=victim.pk).exists()
