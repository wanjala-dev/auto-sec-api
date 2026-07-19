"""ORM-backed FollowWriterPort.

"A follows B" is represented as ``A ∈ B.profile.followers``. Adding to a
M2M set is idempotent, so retries are safe.
"""

from __future__ import annotations

from uuid import UUID

from components.social.application.ports.follow_writer_port import FollowWriterPort
from infrastructure.persistence.users.models import UserProfile


class DjangoFollowWriter(FollowWriterPort):
    def add_follow(self, *, follower_id: UUID, followee_id: UUID) -> None:
        if follower_id == followee_id:
            return
        profile = UserProfile.objects.filter(user_id=followee_id).first()
        if profile is None:
            return
        profile.followers.add(follower_id)
