"""URL configuration for the social bounded context.

Serves the WORKSPACE FEED — the operator feed the HUD renders. Mounted at
``/social/`` in the root URL configuration.

The legacy generic CRUD surface that used to live here (``/social/``,
``/social/<int:pk>/``, ``/social/comment``, ``/social/comment/<int:pk>/``)
was RETIRED: it had no consumer in any client and every social defect found
in the 2026-08-19 sweep lived on it. See the module docstring of
``controller.py`` for the full account.

NOTE: Messaging (threads, messages, inbox) has been extracted to
``components.messaging``.  See ``/messaging/`` endpoints.
"""

from django.urls import path

from components.social.api.controller import (
    WorkspaceFeedPostCommentsView,
    WorkspaceFeedPostDetail,
    WorkspaceFeedPostLikeView,
    WorkspaceFeedView,
)

urlpatterns = [
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
