"""Post ORM ↔ domain entity mapper."""

from __future__ import annotations

from infrastructure.persistence.social.models import Post

from components.social.domain.entities.post_entity import PostEntity, PostVisibility


def to_post_entity(model: Post) -> PostEntity:
    image_ids: tuple[int, ...] = tuple(
        getattr(model, "_prefetched_image_ids", None)
        or model.image.values_list("id", flat=True)
    )
    like_count = getattr(model, "like_count", None)
    if like_count is None:
        like_count = model.likes.count()
    comment_count = getattr(model, "comment_count", None)
    if comment_count is None:
        comment_count = model.comment_set.count()
    return PostEntity(
        id=model.id,
        author_id=model.author_id,
        workspace_id=model.workspace_id,
        team_id=model.team_id,
        visibility=PostVisibility(model.visibility),
        body=model.body,
        image_ids=image_ids,
        created_on=model.created_on,
        edited_on=model.edited_on,
        is_pinned=model.is_pinned,
        is_deleted=model.is_deleted,
        like_count=like_count,
        comment_count=comment_count,
    )
