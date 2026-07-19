"""Composition root for the workspace-feed use cases.

Wires ports to their concrete Django adapters so controllers stay thin.
"""

from __future__ import annotations

from components.social.application.use_cases.auto_follow_workspace_members_use_case import (
    AutoFollowWorkspaceMembersUseCase,
)
from components.social.application.use_cases.create_workspace_post_use_case import (
    CreateWorkspacePostUseCase,
)
from components.social.application.use_cases.delete_post_use_case import (
    DeletePostUseCase,
)
from components.social.application.use_cases.edit_post_use_case import EditPostUseCase
from components.social.application.use_cases.list_workspace_feed_use_case import (
    ListWorkspaceFeedUseCase,
)
from components.social.infrastructure.adapters.django_follow_reader import (
    DjangoFollowReader,
)
from components.social.infrastructure.adapters.django_follow_writer import (
    DjangoFollowWriter,
)
from components.social.infrastructure.adapters.django_workspace_membership_reader import (
    DjangoWorkspaceMembershipReader,
)
from components.social.infrastructure.repositories.feed_post_repository import (
    FeedPostRepository,
)


class FeedProvider:
    @staticmethod
    def list_feed_use_case() -> ListWorkspaceFeedUseCase:
        return ListWorkspaceFeedUseCase(
            post_store=FeedPostRepository(),
            follows=DjangoFollowReader(),
            memberships=DjangoWorkspaceMembershipReader(),
        )

    @staticmethod
    def create_post_use_case() -> CreateWorkspacePostUseCase:
        return CreateWorkspacePostUseCase(
            post_store=FeedPostRepository(),
            memberships=DjangoWorkspaceMembershipReader(),
        )

    @staticmethod
    def edit_post_use_case() -> EditPostUseCase:
        return EditPostUseCase(post_store=FeedPostRepository())

    @staticmethod
    def delete_post_use_case() -> DeletePostUseCase:
        return DeletePostUseCase(
            post_store=FeedPostRepository(),
            memberships=DjangoWorkspaceMembershipReader(),
        )

    @staticmethod
    def auto_follow_use_case() -> AutoFollowWorkspaceMembersUseCase:
        return AutoFollowWorkspaceMembersUseCase(
            follow_writer=DjangoFollowWriter(),
            memberships=DjangoWorkspaceMembershipReader(),
        )
