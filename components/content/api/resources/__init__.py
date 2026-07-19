"""Resource DTOs for content bounded context."""

from __future__ import annotations

from .news import NewsResource, NewsCollectionResource, UserSummary as NewsUserSummary, FileResource, TagResource, CommentResource as NewsCommentResource
from .comment import CommentResource, CommentCollectionResource, UserSummary as CommentUserSummary
from .category import CategoryResource, CategoryCollectionResource

__all__ = [
    'NewsResource',
    'NewsCollectionResource',
    'NewsUserSummary',
    'FileResource',
    'TagResource',
    'NewsCommentResource',
    'CommentResource',
    'CommentCollectionResource',
    'CommentUserSummary',
    'CategoryResource',
    'CategoryCollectionResource',
]
