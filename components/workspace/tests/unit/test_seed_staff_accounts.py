from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.use_cases.seed_staff_accounts_use_case import (
    SeedStaffAccountsUseCase,
)


def test_seed_staff_accounts_adds_members_and_sets_profile_defaults():
    store = SimpleNamespace(ensure_staff_member=Mock())
    staff_team = SimpleNamespace(id="staff-team", workspace_id="workspace-1")
    contributors_team = SimpleNamespace(id="contributors-team", workspace_id="workspace-1")

    SeedStaffAccountsUseCase(
        staff_account_store=store,
    ).execute(
        [
            {
                "email": "teammate@example.com",
                "first_name": "Test",
                "last_name": "User",
            }
        ],
        staff_team=staff_team,
        contributors_team=contributors_team,
    )

    store.ensure_staff_member.assert_called_once()
    kwargs = store.ensure_staff_member.call_args.kwargs
    assert kwargs["email"] == "teammate@example.com"
    assert kwargs["username"] == "test-user"
    assert kwargs["staff_team"] is staff_team
    assert kwargs["contributors_team"] is contributors_team
    assert "dicebear" in kwargs["photo_url"]
