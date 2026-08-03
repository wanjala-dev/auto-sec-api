"""Port: read/write the workspace triage-agent's gated capability config.

``SetWorkspaceAgentCapabilityUseCase`` is the owner-facing setter for the ADR-0010
draft-PR capability: it ensures the workspace's ``triage_agent`` row exists,
merges a single capability flag into ``Agent.config['capabilities']``, and reads
the current capability map. Those reads/writes used to touch the ``Agent`` ORM
directly from the application layer (Rule-2 violation). This port is the
sanctioned seam — the ORM lives in the adapter, the use case keeps the
deterministic allowlist / coercion / audit logic.

The returned :class:`AgentCapabilityRow` is a thin frozen carrier of exactly the
fields the use case needs to audit and report — the ORM ``Agent`` instance never
crosses the port (except as the audit ``instance`` handle, which the audit
provider treats opaquely; see :meth:`AgentCapabilityPort.get_or_create_triage_agent`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentCapabilityRow:
    """The triage-agent capability facts the use case operates on.

    ``instance`` is the ORM row handle, passed straight back to the audit
    provider (which reads it opaquely for its content-type/field-change record).
    ``capabilities`` is a copy of ``config['capabilities']`` (never the live
    mutable dict). ``created`` is True when the row was provisioned by this call.
    """

    agent_id: str
    capabilities: dict[str, bool] = field(default_factory=dict)
    created: bool = False
    instance: Any = None


class AgentCapabilityPort(ABC):
    """Read/write the workspace triage-agent's capability config."""

    @abstractmethod
    def get_or_create_triage_agent(self, *, workspace: Any, actor: Any) -> AgentCapabilityRow:
        """Return the workspace's most-recent ``triage_agent`` row, creating one
        (owned by the workspace owner, falling back to ``actor``) if none exists.

        Mirrors ``OpenDraftPrUseCase._require_capability``'s row resolution
        (``order_by('-created_at').first()``) so the row this touches is the same
        row the gate consults.
        """

    @abstractmethod
    def set_capabilities(self, *, agent: Any, capabilities: dict[str, bool]) -> None:
        """Persist ``capabilities`` onto ``Agent.config['capabilities']`` for the
        given row, leaving the rest of ``config`` untouched.
        """

    @abstractmethod
    def get_triage_capabilities(self, *, workspace_id: str) -> dict[str, bool]:
        """Return the stored ``capabilities`` map for the workspace's triage
        agent, or ``{}`` when no row / no capabilities exist. Read-only — never
        provisions a row.
        """
