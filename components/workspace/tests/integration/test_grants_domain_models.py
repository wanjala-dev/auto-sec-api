import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from infrastructure.persistence.workspaces.models import (
    Grant,
    GrantAllocation,
    GrantChecklistItem,
    GrantReminder,
)


pytestmark = pytest.mark.django_db


def test_grant_domain_models_create_successfully(workspace_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner

    grant = Grant.objects.create(
        workspace=workspace,
        owner=owner,
        title="Community Innovation Grant",
        funder_name="Impact Fund",
        amount_requested=Decimal("50000.00"),
        status=Grant.Status.OPEN,
        submission_deadline=datetime.date.today() + datetime.timedelta(days=14),
    )

    checklist = GrantChecklistItem.objects.create(
        grant=grant,
        title="Collect board approval letter",
        created_by=owner,
        order=1,
    )

    reminder = GrantReminder.objects.create(
        grant=grant,
        remind_at=timezone.now() + datetime.timedelta(days=2),
        message="Submit draft budget attachments",
        created_by=owner,
    )

    allocation = GrantAllocation.objects.create(
        grant=grant,
        workspace=workspace,
        name="Program delivery",
        amount=Decimal("15000.00"),
        allocation_percent=Decimal("30.00"),
        created_by=owner,
    )

    assert grant.workspace_id == workspace.id
    assert checklist.grant_id == grant.id
    assert reminder.grant_id == grant.id
    assert allocation.grant_id == grant.id
    assert allocation.workspace_id == workspace.id


def test_grant_reminder_default_channel_is_in_app(workspace_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    grant = Grant.objects.create(workspace=workspace, owner=owner, title="Pilot Grant")

    reminder = GrantReminder.objects.create(
        grant=grant,
        remind_at=timezone.now() + datetime.timedelta(hours=12),
        message="Review checklist",
        created_by=owner,
    )

    assert reminder.channel == GrantReminder.Channel.IN_APP
