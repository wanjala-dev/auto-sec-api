"""Resource DTOs for like/dislike endpoints.

Output data classes for POST like/dislike responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LikeActionResource:
    """Output DTO for POST /social/<id>/like endpoint response."""
    status: str
    code: int
    message: str


@dataclass(frozen=True)
class DislikeActionResource:
    """Output DTO for POST /social/<id>/dislike endpoint response."""
    status: str
    code: int
    message: str


@dataclass(frozen=True)
class CommentLikeActionResource:
    """Output DTO for POST /social/comment/<id>/like endpoint response."""
    status: str
    code: int
    message: str


@dataclass(frozen=True)
class CommentDislikeActionResource:
    """Output DTO for POST /social/comment/<id>/dislike endpoint response."""
    status: str
    code: int
    message: str
