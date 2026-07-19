"""Request DTOs for the social bounded context.

Input data classes for all write endpoints in the social API.
"""

from components.social.api.requests.comment_requests import (
    CreateCommentReplyRequest,
    CreateCommentRequest,
    UpdateCommentRequest,
)
from components.social.api.requests.follower_requests import (
    AddFollowerRequest,
    RemoveFollowerRequest,
)
from components.social.api.requests.like_requests import (
    AddCommentDislikeRequest,
    AddCommentLikeRequest,
    AddDislikeRequest,
    AddLikeRequest,
)
from components.social.api.requests.message_requests import (
    CreateMessageRequest,
    UpdateMessageRequest,
)
from components.social.api.requests.post_requests import (
    CreatePostRequest,
    UpdatePostRequest,
)
from components.social.api.requests.tag_requests import (
    CreateTagRequest,
    UpdateTagRequest,
)
from components.social.api.requests.thread_requests import (
    CreateThreadRequest,
    ThreadArchiveRequest,
    ThreadStarRequest,
    ThreadUnarchiveRequest,
    ThreadUnstarRequest,
)

__all__ = [
    # Post requests
    "CreatePostRequest",
    "UpdatePostRequest",
    # Comment requests
    "CreateCommentRequest",
    "UpdateCommentRequest",
    "CreateCommentReplyRequest",
    # Like requests
    "AddLikeRequest",
    "AddDislikeRequest",
    "AddCommentLikeRequest",
    "AddCommentDislikeRequest",
    # Tag requests
    "CreateTagRequest",
    "UpdateTagRequest",
    # Thread requests
    "CreateThreadRequest",
    "ThreadArchiveRequest",
    "ThreadUnarchiveRequest",
    "ThreadStarRequest",
    "ThreadUnstarRequest",
    # Message requests
    "CreateMessageRequest",
    "UpdateMessageRequest",
    # Follower requests
    "AddFollowerRequest",
    "RemoveFollowerRequest",
]
