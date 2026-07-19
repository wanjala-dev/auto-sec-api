"""ORM-backed FollowReaderPort.

Reads :class:`UserProfile.followers`, which is a M2M from the profile owner
to the users who follow them. "A follows B" ↔ "A ∈ B.profile.followers".
"""

from __future__ import annotations

from typing import FrozenSet
from uuid import UUID

from components.social.application.ports.follow_reader_port import FollowReaderPort
from infrastructure.persistence.users.models import UserProfile


class DjangoFollowReader(FollowReaderPort):
    def list_followed_user_ids(self, user_id: UUID) -> FrozenSet[UUID]:
        return frozenset(
            UserProfile.objects
            .filter(followers__id=user_id)
            .values_list("user_id", flat=True)
        )

    def is_following(self, *, user_id: UUID, target_id: UUID) -> bool:
        return UserProfile.objects.filter(
            user_id=target_id, followers__id=user_id
        ).exists()
