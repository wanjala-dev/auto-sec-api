"""Port: monthly AI-run quota checks (metered AI — Free/Pro/Premium tiers).

No Django imports — depends only on standard library. The adapter that
implements this port owns the ORM counting + entitlement resolution.

A "run" is a *billable* agent execution: a one-shot ``execute`` or a
``deep_run`` (plan / plan-and-run). Conversational ``chat`` is NOT a run —
it is free on every tier (see ``AgentsService.agent_chat`` vs the metered
methods). The two run types persist to *different* tables —
``AgentExecution`` for ``execute``, ``DeepRun`` for deep runs — so the
usage count is the SUM of both for the workspace's current calendar month.
Counting only one would silently under-meter the other (a broken gate).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class AiRunQuotaStatus:
    """Outcome of a monthly AI-run quota check for one workspace.

    ``limit is None`` means UNLIMITED (Premium, or a workspace with no
    tiered plan) — ``allowed`` is then always ``True`` and ``used`` is
    still reported for observability.
    """

    allowed: bool
    used: int
    limit: int | None
    workspace_id: str | None

    @property
    def is_unlimited(self) -> bool:
        return self.limit is None


class AiRunQuotaPort(abc.ABC):
    """Secondary port: resolve a workspace's remaining monthly AI-run allowance."""

    @abc.abstractmethod
    def check_for_workspace(self, workspace_id: str | None) -> AiRunQuotaStatus:
        """Quota status for a workspace id (used by the deep-run path).

        A falsy / unknown workspace resolves to UNLIMITED (fail-open) — a
        run with no tier context can't be tier-gated.
        """
        ...

    @abc.abstractmethod
    def check_for_agent(self, agent_id: str | None) -> AiRunQuotaStatus:
        """Quota status for the workspace that owns ``agent_id``.

        Used by the one-shot ``execute`` path, whose command carries only
        an ``agent_id`` (no ``workspace_id``). Resolves the agent's
        workspace, then delegates to :meth:`check_for_workspace`. An
        unknown agent or a workspace-less agent resolves to UNLIMITED.
        """
        ...

    @abc.abstractmethod
    def record_run(self, workspace_id: str | None) -> None:
        """Record one billable AI run against the workspace's monthly tally.

        Called by the metered chokepoints AFTER a run is accepted — never on
        the chat path. A falsy workspace id is a no-op (nothing to meter).
        """
        ...
