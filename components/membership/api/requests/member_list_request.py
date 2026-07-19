"""Input DTO for member list queries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemberListRequest:
    """Input DTO for GET /membership/members/ endpoint."""

    workspace_id: str
