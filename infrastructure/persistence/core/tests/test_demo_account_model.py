"""Tests for the DemoAccount registry model."""

import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from infrastructure.persistence.core.models import DemoAccount

logger = logging.getLogger(__name__)


@pytest.mark.django_db
class TestDemoAccountModel:
    def test_fields_persist(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        user = user_factory()
        expires_at = timezone.now() + timedelta(days=7)

        account = DemoAccount.objects.create(
            workspace=workspace,
            user=user,
            persona="sponsor",
            org_slug="jeremiah-house",
            label="Melissa — Jeremiah House",
            stripe_account_id="acct_test_123",
            expires_at=expires_at,
            provisioned_by="provision-demo-cli",
        )

        account.refresh_from_db()
        assert account.workspace_id == workspace.id
        assert account.user_id == user.id
        assert account.persona == "sponsor"
        assert account.org_slug == "jeremiah-house"
        assert account.label == "Melissa — Jeremiah House"
        assert account.stripe_account_id == "acct_test_123"
        assert account.expires_at == expires_at
        assert account.provisioned_by == "provision-demo-cli"
        assert account.created_at is not None

    def test_status_defaults_to_active(self, workspace_factory, user_factory):
        account = DemoAccount.objects.create(
            workspace=workspace_factory(),
            user=user_factory(),
            persona="admin",
        )
        assert account.status == DemoAccount.Status.ACTIVE
        assert account.status == "active"

    def test_is_expired_false_for_future_expiry(self, workspace_factory, user_factory):
        account = DemoAccount.objects.create(
            workspace=workspace_factory(),
            user=user_factory(),
            persona="contributor",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        assert account.is_expired is False

    def test_is_expired_true_for_past_expiry(self, workspace_factory, user_factory):
        account = DemoAccount.objects.create(
            workspace=workspace_factory(),
            user=user_factory(),
            persona="contributor",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        assert account.is_expired is True

    def test_is_expired_false_when_no_expiry(self, workspace_factory, user_factory):
        account = DemoAccount.objects.create(
            workspace=workspace_factory(),
            user=user_factory(),
            persona="admin",
            expires_at=None,
        )
        assert account.is_expired is False
