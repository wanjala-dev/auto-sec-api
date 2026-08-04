"""Command + result for tagging/untagging a finding (ADR 0015 D6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.shared_kernel.domain.tagging import TagRef


@dataclass(frozen=True)
class TagFindingCommand:
    workspace_id: UUID
    finding_id: UUID
    add: tuple[str, ...]  # slugs (or raw names — normalized via tag_slug.py)
    remove: tuple[str, ...]
    actor_id: str | None
    at: datetime


@dataclass(frozen=True)
class TagFindingResult:
    """The finding's full post-change tag set — the HUD chip row re-renders from this."""

    finding_id: UUID
    tags: tuple[TagRef, ...]
