"""Value objects for the messaging domain."""

from __future__ import annotations

import enum


class ConversationType(str, enum.Enum):
    PRIVATE = "private"
    WORKSPACE = "workspace"


class ParticipantRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class MessageType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    SYSTEM = "system"
