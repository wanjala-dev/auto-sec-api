"""Provider for social ORM models.

Gives controllers a single dependency-inversion seam over
``infrastructure.persistence.social.models`` so the explicit-architecture
rule (controllers don't import ORM modules directly) holds.

Each property lazy-imports its model class inside the method body so this
module stays framework-free at import time — only stdlib + ``typing`` at
the top level. Call sites unchanged: ``Comment = provider.Comment`` then
``Comment.objects.filter(...)`` works exactly as before.
"""

from __future__ import annotations

from typing import Any


class SocialModelsProvider:
    """Façade over ``infrastructure.persistence.social`` ORM models."""

    @property
    def Post(self) -> Any:
        from infrastructure.persistence.social.models import Post
        return Post

    @property
    def Comment(self) -> Any:
        from infrastructure.persistence.social.models import Comment
        return Comment

    @property
    def ThreadModel(self) -> Any:
        from infrastructure.persistence.social.models import ThreadModel
        return ThreadModel

    @property
    def MessageModel(self) -> Any:
        from infrastructure.persistence.social.models import MessageModel
        return MessageModel

    @property
    def Image(self) -> Any:
        from infrastructure.persistence.social.models import Image
        return Image

    @property
    def Tag(self) -> Any:
        from infrastructure.persistence.social.models import Tag
        return Tag


_default = SocialModelsProvider()


def get_social_models_provider() -> SocialModelsProvider:
    """Return the process-wide default :class:`SocialModelsProvider`."""
    return _default
