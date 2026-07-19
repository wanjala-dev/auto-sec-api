"""Port for loading workspace AI configuration + tracking usage."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.agents.domain.value_objects.workspace_ai_config import WorkspaceAIConfig


class WorkspaceAIConfigPort(ABC):
    """Load + save workspace AI config and track per-workspace usage.

    The config side is value-object oriented (load returns a
    ``WorkspaceAIConfig``, save persists it). The usage side talks in
    plain integer counters because the GTM cost gate just needs
    "messages today" / "tokens this month" / "increment by N".
    """

    # ── Config ───────────────────────────────────────────────────────

    @abstractmethod
    def load(self, workspace_id: str) -> WorkspaceAIConfig:
        """Load AI config for a workspace. Returns defaults if not configured."""
        ...

    @abstractmethod
    def save(self, workspace_id: str, config: WorkspaceAIConfig) -> None:
        """Persist AI config for a workspace."""
        ...

    # ── Per-user usage (legacy — drives the PersonaAILimits cap) ─────

    @abstractmethod
    def get_messages_used_today(self, workspace_id: str, user_id: str) -> int:
        """Return how many AI messages this user has sent today."""
        ...

    # ── Per-workspace usage (the GTM cost gate added in PR #5) ───────

    @abstractmethod
    def get_workspace_messages_today(self, workspace_id: str) -> int:
        """Total AI chat messages sent across the workspace today (UTC)."""
        ...

    @abstractmethod
    def get_workspace_tokens_this_month(self, workspace_id: str) -> int:
        """Total LLM tokens (prompt + completion) used this month (UTC)."""
        ...

    @abstractmethod
    def get_workspace_runs_this_month(self, workspace_id: str) -> int:
        """Metered-AI runs (execute + deep_run) used this month (UTC)."""
        ...

    @abstractmethod
    def record_workspace_run(self, workspace_id: str, *, runs: int = 1) -> None:
        """Atomically tally metered-AI runs for the month (own window)."""
        ...

    @abstractmethod
    def increment_workspace_usage(
        self,
        workspace_id: str,
        *,
        messages: int = 1,
        tokens: int = 0,
    ) -> None:
        """Atomically bump the workspace's running counters.

        Implementations MUST use a single-row atomic update (e.g. Django
        ``F()`` expression) so concurrent chat calls don't race and lose
        increments. Rollover from yesterday → today (or last-month →
        this-month) is handled by the daily/monthly reset Celery beat
        tasks; the increment path stays simple and just bumps the row.
        """
        ...
