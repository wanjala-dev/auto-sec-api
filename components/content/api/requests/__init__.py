"""Request DTOs for content bounded context."""

from __future__ import annotations

from .news import CreateNewsRequest, UpdateNewsRequest
from .comment import CreateCommentRequest, CreateCommentReplyRequest
from .category import CreateCategoryRequest

__all__ = [
    'CreateNewsRequest',
    'UpdateNewsRequest',
    'CreateCommentRequest',
    'CreateCommentReplyRequest',
    'CreateCategoryRequest',
]
