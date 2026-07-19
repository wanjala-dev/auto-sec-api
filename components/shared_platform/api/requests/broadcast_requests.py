"""Request DTOs for Broadcast/Announcements endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CreateBannerRequest:
    """Input DTO for POST /banners/ endpoint."""
    title: str
    message: str
    scope: str
    priority: int = 0
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    is_active: bool = True


@dataclass(frozen=True)
class UpdateBannerRequest:
    """Input DTO for PUT/PATCH /banners/{id}/ endpoints."""
    title: Optional[str] = None
    message: Optional[str] = None
    scope: Optional[str] = None
    priority: Optional[int] = None
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    is_active: Optional[bool] = None
