"""URL configuration for the social bounded context.

Provides CRUD endpoints for posts, comments, tags.
Mounted at ``/social/`` in the root URL configuration.

NOTE: Messaging (threads, messages, inbox) has been extracted to
``components.messaging``.  See ``/messaging/`` endpoints.
"""

from django.urls import path

from components.social.api.controller import (
    CommentDetail,
    CommentList,
    PostDetail,
    PostList,
    WorkspaceFeedPostCommentsView,
    WorkspaceFeedPostDetail,
    WorkspaceFeedPostLikeView,
    WorkspaceFeedView,
)

urlpatterns = [
    path("", PostList.as_view(), name=PostList.name),
    path("<int:pk>/", PostDetail.as_view(), name=PostDetail.name),
    path("comment", CommentList.as_view(), name=CommentList.name),
    path("comment/<int:pk>/", CommentDetail.as_view(), name=CommentDetail.name),
    # Workspace feed
    path(
        "workspaces/<uuid:workspace_id>/feed/",
        WorkspaceFeedView.as_view(),
        name=WorkspaceFeedView.name,
    ),
    path(
        "posts/<int:post_id>/",
        WorkspaceFeedPostDetail.as_view(),
        name=WorkspaceFeedPostDetail.name,
    ),
    path(
        "posts/<int:pk>/like/",
        WorkspaceFeedPostLikeView.as_view(),
        name=WorkspaceFeedPostLikeView.name,
    ),
    path(
        "posts/<int:pk>/comments/",
        WorkspaceFeedPostCommentsView.as_view(),
        name=WorkspaceFeedPostCommentsView.name,
    ),
]
