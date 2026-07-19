"""Feed visibility policy.

Pure function describing whether a given viewer can see a given post. The
actual follow / membership lookups happen in ports; this module only owns
the decision tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet
from uuid import UUID

from components.social.domain.entities.post_entity import PostEntity, PostVisibility


@dataclass(frozen=True)
class ViewerContext:
    """Everything the policy needs about the caller.

    ``followed_user_ids`` is the set of user IDs the viewer follows.
    ``workspace_member_ids`` is the set of user IDs who are members of the
    post's workspace. ``viewer_team_ids`` is the set of team IDs the viewer
    belongs to. ``is_workspace_owner`` short-circuits to visible.
    """

    viewer_id: UUID
    followed_user_ids: FrozenSet[UUID]
    workspace_member_ids: FrozenSet[UUID]
    viewer_team_ids: FrozenSet[int]
    is_workspace_owner: bool


def is_post_visible(post: PostEntity, viewer: ViewerContext) -> bool:
    if post.is_deleted:
        return False
    # Author always sees their own posts.
    if post.author_id == viewer.viewer_id:
        return True
    # Owners see everything in workspaces they own.
    if viewer.is_workspace_owner:
        return True

    if post.visibility == PostVisibility.PUBLIC:
        return True

    if post.visibility == PostVisibility.WORKSPACE:
        if post.author_id not in viewer.workspace_member_ids:
            return False
        return post.author_id in viewer.followed_user_ids

    if post.visibility == PostVisibility.TEAM:
        if post.team_id is None or post.team_id not in viewer.viewer_team_ids:
            return False
        return post.author_id in viewer.followed_user_ids

    return False
