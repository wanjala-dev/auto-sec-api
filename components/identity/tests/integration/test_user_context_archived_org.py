"""Integration test: archived (status="inactive") workspaces must not leak into
the user-context accessible-workspace list / org count.

Regression for the demo 404 storm: an owner's archived org surfaced in
me/summary's ``workspace_context.org_workspace_ids`` (because the repo queried
``Workspace.objects.all_objects()`` — no status filter) while the active-only
member ``workspaces`` list excluded it. The frontend enumerated org_workspace_ids
and 404'd fetching the archived org. The fix queries the default manager
(``status="active"``) so the two lists agree.

These hit the real ORM on purpose — the bug lived in the queryset manager, which
a fake port can't exercise.
"""
from __future__ import annotations

import pytest

from components.identity.infrastructure.repositories.orm_user_context_query_repository import (
    OrmUserContextQueryRepository,
)


@pytest.mark.django_db
class TestArchivedOrgExcludedFromUserContext:
    def test_archived_owned_workspace_excluded_from_accessible_ids(
        self, user_factory, workspace_factory
    ):
        user = user_factory()
        active = workspace_factory(owner=user, status="active")
        archived = workspace_factory(owner=user, status="inactive")

        ids = OrmUserContextQueryRepository().get_accessible_workspace_ids(user_id=user.id)

        assert str(active.id) in ids
        assert str(archived.id) not in ids
        assert ids == [str(active.id)]

    def test_archived_owned_workspace_not_counted(self, user_factory, workspace_factory):
        user = user_factory()
        workspace_factory(owner=user, status="active")
        workspace_factory(owner=user, status="inactive")

        # Only the active workspace counts; the archived one must not inflate it.
        assert OrmUserContextQueryRepository().get_org_membership_count(user_id=user.id) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
