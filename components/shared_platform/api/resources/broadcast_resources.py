"""Resource DTOs for Broadcast/Announcements entities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BannerResource:
    """Output DTO for banner detail endpoints."""
    id: int
    title: str
    message: str
    scope: str
    priority: int
    is_active: bool
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class BannerCollectionResource:
    """Output DTO for banner list endpoints."""
    items: list[BannerResource]
    count: int = 0
