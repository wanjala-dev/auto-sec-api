"""Resource DTOs for the social bounded context.

Output data classes for all read/write endpoints in the social API.
"""

from components.social.api.resources.comment_resources import (
    CommentCollectionResource,
    CommentResource,
)
from components.social.api.resources.follower_resources import (
    FollowerActionResource,
    FollowerCollectionResource,
    FollowerResource,
)
from components.social.api.resources.like_resources import (
    CommentDislikeActionResource,
    CommentLikeActionResource,
    DislikeActionResource,
    LikeActionResource,
)
from components.social.api.resources.message_resources import (
    MessageCollectionResource,
    MessageResource,
)
from components.social.api.resources.post_resources import (
    PostCollectionResource,
    PostResource,
    TagResource,
)
from components.social.api.resources.tag_resources import (
    TagCollectionResource,
    TagResource as TagDetailResource,
)
from components.social.api.resources.thread_resources import (
    ThreadActionResource,
    ThreadCollectionResource,
    ThreadResource,
)

__all__ = [
    # Post resources
    "PostResource",
    "PostCollectionResource",
    "TagResource",
    # Comment resources
    "CommentResource",
    "CommentCollectionResource",
    # Like resources
    "LikeActionResource",
    "DislikeActionResource",
    "CommentLikeActionResource",
    "CommentDislikeActionResource",
    # Tag resources
    "TagDetailResource",
    "TagCollectionResource",
    # Thread resources
    "ThreadResource",
    "ThreadCollectionResource",
    "ThreadActionResource",
    # Message resources
    "MessageResource",
    "MessageCollectionResource",
    # Follower resources
    "FollowerResource",
    "FollowerCollectionResource",
    "FollowerActionResource",
]
