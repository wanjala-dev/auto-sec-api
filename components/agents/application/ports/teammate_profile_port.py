"""Port: Teammate profile read/write operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GetTeammateProfileRequest:
    workspace_id: str
    user: Any = None


@dataclass
class TeammateProfileData:
    workspace_id: str = ""
    display_name: str | None = None
    avatar_url: str = ""


@dataclass(frozen=True)
class UpdateTeammateProfileCommand:
    workspace_id: str
    user: Any = None
    display_name: str | None = None
    # ``None`` = leave untouched (PATCH semantics); "" = clear back to
    # the platform default avatar.
    avatar_url: str | None = None


@dataclass
class UpdateTeammateProfileResult:
    workspace_id: str = ""
    display_name: str | None = None
    avatar_url: str = ""


class TeammateProfilePort(abc.ABC):
    """Secondary port for teammate profile operations."""

    @abc.abstractmethod
    def get_teammate_profile(self, *, request: GetTeammateProfileRequest) -> TeammateProfileData:
        """Fetch teammate profile display name.

        Raises LookupError if workspace not found.
        Raises PermissionError if user lacks access.
        """
        ...

    @abc.abstractmethod
    def update_teammate_profile(self, *, command: UpdateTeammateProfileCommand) -> UpdateTeammateProfileResult:
        """Update teammate profile display name.

        Raises LookupError if workspace not found.
        Raises PermissionError if user lacks access.
        """
        ...
