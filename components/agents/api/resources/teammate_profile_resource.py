"""Response DTO for teammate profile endpoints."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeammateProfileResource:
    """Output DTO for teammate profile endpoints."""
    workspace_id: str
    display_name: str | None = None
    avatar_url: str = ""
