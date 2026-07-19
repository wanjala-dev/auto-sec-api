"""Request DTO for listing conversations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationListRequest:
    """Input DTO for fetching conversations."""

    include_archived: bool = False
    starred_only: bool = False
