"""Request DTOs for like/dislike endpoints.

Input data classes for like/dislike operations (typically stateless POST actions).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AddLikeRequest:
    """Input DTO for POST /social/<id>/like endpoint."""
    pass


@dataclass(frozen=True)
class AddDislikeRequest:
    """Input DTO for POST /social/<id>/dislike endpoint."""
    pass


@dataclass(frozen=True)
class AddCommentLikeRequest:
    """Input DTO for POST /social/comment/<id>/like endpoint."""
    pass


@dataclass(frozen=True)
class AddCommentDislikeRequest:
    """Input DTO for POST /social/comment/<id>/dislike endpoint."""
    pass
