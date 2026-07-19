"""Resource DTOs for workspace bounded context API endpoints."""

from __future__ import annotations

from components.workspace.api.resources.action_resource import (
    ActionCollectionResource,
    ActionResource,
)
from components.workspace.api.resources.comment_resource import (
    CommentCollectionResource,
    CommentResource,
)
from components.workspace.api.resources.contribution_means_resource import (
    ContributionMeansCollectionResource,
    ContributionMeansResource,
)
from components.workspace.api.resources.country_resource import (
    CountryCollectionResource,
    CountryResource,
)
from components.workspace.api.resources.tag_resource import (
    TagCollectionResource,
    TagResource,
)
from components.workspace.api.resources.team_resource import (
    TeamCollectionResource,
    TeamResource,
)
from components.workspace.api.resources.workspace_card_resource import (
    WorkspaceCardCollectionResource,
    WorkspaceCardResource,
)
from components.workspace.api.resources.workspace_category_resource import (
    SubCategoryResource,
    WorkspaceCategoryCollectionResource,
    WorkspaceCategoryResource,
)
from components.workspace.api.resources.workspace_follow_resource import (
    WorkspaceFollowResource,
)
from components.workspace.api.resources.workspace_operation_resource import (
    WorkspaceOperationCollectionResource,
    WorkspaceOperationResource,
)
from components.workspace.api.resources.workspace_preference_resource import (
    WorkspacePreferenceCollectionResource,
    WorkspacePreferenceResource,
)
from components.workspace.api.resources.workspace_resource import (
    WorkspaceCollectionResource,
    WorkspaceResource,
)
from components.workspace.api.resources.workspace_setup_status_resource import (
    WorkspaceSetupCheckResource,
    WorkspaceSetupRecommendationResource,
    WorkspaceSetupStatusResource,
)

__all__ = [
    "ActionCollectionResource",
    "ActionResource",
    "CommentCollectionResource",
    "CommentResource",
    "ContributionMeansCollectionResource",
    "ContributionMeansResource",
    "CountryCollectionResource",
    "CountryResource",
    "SubCategoryResource",
    "TagCollectionResource",
    "TagResource",
    "TeamCollectionResource",
    "TeamResource",
    "WorkspaceCardCollectionResource",
    "WorkspaceCardResource",
    "WorkspaceCategoryCollectionResource",
    "WorkspaceCategoryResource",
    "WorkspaceCollectionResource",
    "WorkspaceFollowResource",
    "WorkspaceOperationCollectionResource",
    "WorkspaceOperationResource",
    "WorkspacePreferenceCollectionResource",
    "WorkspacePreferenceResource",
    "WorkspaceResource",
    "WorkspaceSetupCheckResource",
    "WorkspaceSetupRecommendationResource",
    "WorkspaceSetupStatusResource",
]
