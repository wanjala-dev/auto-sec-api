"""Integration tests for ``TeamPlanPaymentSetupRepository``.

These cover the get-or-create idempotency contract on
``ensure_subscription_payment_method``. A prior race condition allowed
two concurrent callers to both pass the "method does not exist" check
and create duplicate ``WorkspacePaymentMethod`` rows with
``metadata.managed_subscription=True`` — observed in prod with
microsecond-identical ``created_at`` timestamps. The fix wraps the
get-or-create in ``transaction.atomic()`` + ``select_for_update()``
on the workspace row.

Single-threaded Python tests can't directly trigger the race, but they
do lock in the contract: calling the function repeatedly on the same
workspace returns exactly one method row.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from components.payments.infrastructure.repositories.team_plan_payment_setup_repository import (
    TeamPlanPaymentSetupRepository,
)
from infrastructure.persistence.workspaces.payments.models import (
    WorkspacePaymentMethod,
)


@pytest.fixture
def setup_repo(payment_provider):
    """Build the repository with a no-op gateway provider.

    ``ensure_subscription_payment_method`` doesn't touch the gateway
    provider — it's only used by ``ensure_team_plan_payment_plan`` for
    Stripe price provisioning. A MagicMock keeps the constructor happy.
    """
    return TeamPlanPaymentSetupRepository(gateway_provider=MagicMock())


@pytest.mark.django_db
def test_ensure_subscription_payment_method_creates_one_row(
    workspace_factory, setup_repo
):
    workspace = workspace_factory()

    method = setup_repo.ensure_subscription_payment_method(workspace=workspace)

    assert method is not None
    assert method.metadata == {"managed_subscription": True}
    assert method.provider_account_id == ""
    assert method.display_name == "Workspace Subscription"
    rows = WorkspacePaymentMethod.objects.filter(
        workspace=workspace,
        metadata__managed_subscription=True,
        is_deleted=False,
    )
    assert rows.count() == 1


@pytest.mark.django_db
def test_ensure_subscription_payment_method_is_idempotent(
    workspace_factory, setup_repo
):
    """Calling the function twice returns the same row, not a duplicate.

    This is the regression: prior to the lock, concurrent calls could
    create two rows for the same workspace.
    """
    workspace = workspace_factory()

    first = setup_repo.ensure_subscription_payment_method(workspace=workspace)
    second = setup_repo.ensure_subscription_payment_method(workspace=workspace)

    assert first.id == second.id
    rows = WorkspacePaymentMethod.objects.filter(
        workspace=workspace,
        metadata__managed_subscription=True,
        is_deleted=False,
    )
    assert rows.count() == 1


@pytest.mark.django_db
def test_ensure_subscription_payment_method_clears_provider_account_id(
    workspace_factory, payment_provider, setup_repo
):
    """If a managed-subscription method somehow ends up with a
    ``provider_account_id`` (e.g. a stale row from before the
    Connect-vs-team-plan separation), the function clears it on next
    call so it stays a platform-level subscription stub.
    """
    workspace = workspace_factory()
    WorkspacePaymentMethod.objects.create(
        workspace=workspace,
        provider=payment_provider,
        display_name="Stale Subscription",
        status=WorkspacePaymentMethod.STATUS_ACTIVE,
        provider_account_id="acct_should_be_cleared",
        metadata={"managed_subscription": True},
        enabled_contexts=["team_plan"],
    )

    method = setup_repo.ensure_subscription_payment_method(workspace=workspace)

    assert method.provider_account_id == ""
