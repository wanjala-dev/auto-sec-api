from django.contrib import admin

from infrastructure.persistence.notifications.userpreferences.models import WorkspacePreference
from infrastructure.persistence.workspaces.models import (
    Action,
    ContributionMeans,
    Grant,
    GrantAllocation,
    GrantChecklistItem,
    GrantReminder,
    SubCategory,
    Tag,
    Workspace,
    WorkspaceCard,
    WorkspaceCategory,
    WorkspaceComment,
    WorkspaceMembership,
    WorkspaceOperations,
)

# auto-sec fork: the payments/billing admin (workspaces.payments) was
# removed with the payments context. Register the kept workspace-core models
# with plain ModelAdmin so the admin site works without referencing dropped
# fields (plan/sector/etc.). Richer admin config can be reintroduced later.
for _model in (
    Workspace,
    WorkspaceMembership,
    WorkspaceCategory,
    SubCategory,
    ContributionMeans,
    WorkspaceComment,
    WorkspaceCard,
    WorkspaceOperations,
    Action,
    Tag,
    Grant,
    GrantChecklistItem,
    GrantReminder,
    GrantAllocation,
    WorkspacePreference,
):
    try:
        admin.site.register(_model)
    except admin.sites.AlreadyRegistered:
        pass
