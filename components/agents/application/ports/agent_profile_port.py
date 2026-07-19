"""Port: Agent profile and state read/write operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GetAgentStateRequest:
    agent_id: str
    user_id: str


@dataclass
class AgentStateData:
    agent_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] | None = None
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False


@dataclass(frozen=True)
class GetAgentProfileRequest:
    agent_id: str
    user: Any = None


@dataclass
class AgentProfileData:
    agent_id: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False


@dataclass(frozen=True)
class PatchAgentProfileCommand:
    agent_id: str
    user: Any = None
    data: dict[str, Any] = field(default_factory=dict)
    http_request: Any = None


@dataclass
class PatchAgentProfileResult:
    agent_id: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False


@dataclass(frozen=True)
class PatchAgentSettingsCommand:
    agent_id: str
    user: Any = None
    data: dict[str, Any] = field(default_factory=dict)
    http_request: Any = None


@dataclass
class PatchAgentSettingsResult:
    profile: dict[str, Any] = field(default_factory=dict)


class AgentProfilePort(abc.ABC):
    """Secondary port for agent profile / state operations."""

    @abc.abstractmethod
    def get_agent_state(self, *, request: GetAgentStateRequest) -> AgentStateData:
        """Fetch agent state + profile + engagement.

        Raises LookupError if agent not found.
        Raises PermissionError if user does not own agent.
        """
        ...

    @abc.abstractmethod
    def get_agent_profile(self, *, request: GetAgentProfileRequest) -> AgentProfileData:
        """Fetch agent profile and engagement counts.

        Raises LookupError if agent not found.
        Raises PermissionError if user lacks access.
        """
        ...

    @abc.abstractmethod
    def patch_agent_profile(self, *, command: PatchAgentProfileCommand) -> PatchAgentProfileResult:
        """Update agent profile fields.

        Raises LookupError if agent not found.
        Raises PermissionError if user lacks manage permission.
        Raises ValueError if data invalid.
        """
        ...

    @abc.abstractmethod
    def patch_agent_settings(self, *, command: PatchAgentSettingsCommand) -> PatchAgentSettingsResult:
        """Update agent custom settings / profile flags.

        Raises LookupError if agent not found.
        Raises PermissionError if user lacks manage permission.
        Raises ValueError if data invalid.
        """
        ...
