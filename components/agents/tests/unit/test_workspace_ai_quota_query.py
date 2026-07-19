"""Unit tests for build_workspace_ai_quota_snapshot."""

from __future__ import annotations

from components.agents.application.queries.workspace_ai_quota_query import (
    build_workspace_ai_quota_snapshot,
)
from components.agents.application.ports.workspace_ai_config_port import (
    WorkspaceAIConfigPort,
)
from components.agents.domain.value_objects.workspace_ai_config import (
    WorkspaceAIConfig,
)


class _StubPort(WorkspaceAIConfigPort):
    """In-memory adapter for unit tests — no DB."""

    def __init__(
        self,
        *,
        config: WorkspaceAIConfig,
        workspace_messages_today: int = 0,
        workspace_tokens_this_month: int = 0,
    ):
        self._config = config
        self._daily = workspace_messages_today
        self._monthly = workspace_tokens_this_month
        self.last_increment: tuple[int, int] | None = None

    def load(self, workspace_id):
        return self._config

    def save(self, workspace_id, config):
        self._config = config

    def get_messages_used_today(self, workspace_id, user_id):
        return 0

    def get_workspace_messages_today(self, workspace_id):
        return self._daily

    def get_workspace_tokens_this_month(self, workspace_id):
        return self._monthly

    def get_workspace_runs_this_month(self, workspace_id):
        return 0

    def record_workspace_run(self, workspace_id, *, runs=1):
        self.last_run_increment = runs

    def increment_workspace_usage(self, workspace_id, *, messages=1, tokens=0):
        self.last_increment = (messages, tokens)


class TestBuildWorkspaceAIQuotaSnapshot:
    def test_basic_snapshot_shape(self):
        port = _StubPort(
            config=WorkspaceAIConfig(
                workspace_daily_message_budget=100,
                monthly_token_budget=1_000_000,
            ),
            workspace_messages_today=42,
            workspace_tokens_this_month=250_000,
        )
        snapshot = build_workspace_ai_quota_snapshot(
            "ws-1", ai_config_port=port
        )
        assert snapshot["ai_enabled"] is True
        assert snapshot["daily_message_budget"] == 100
        assert snapshot["daily_messages_used"] == 42
        assert snapshot["daily_messages_remaining"] == 58
        assert snapshot["monthly_token_budget"] == 1_000_000
        assert snapshot["monthly_tokens_used"] == 250_000
        assert snapshot["monthly_tokens_remaining"] == 750_000

    def test_at_limit_remaining_is_zero(self):
        port = _StubPort(
            config=WorkspaceAIConfig(workspace_daily_message_budget=100),
            workspace_messages_today=100,
        )
        snapshot = build_workspace_ai_quota_snapshot("ws-1", ai_config_port=port)
        assert snapshot["daily_messages_remaining"] == 0

    def test_over_limit_remaining_clamped_to_zero(self):
        # If somehow the counter overshot the budget (e.g. race during
        # the rollover window), the remaining value should clamp to 0
        # not go negative — frontend expects an unsigned int.
        port = _StubPort(
            config=WorkspaceAIConfig(workspace_daily_message_budget=100),
            workspace_messages_today=105,
        )
        snapshot = build_workspace_ai_quota_snapshot("ws-1", ai_config_port=port)
        assert snapshot["daily_messages_remaining"] == 0

    def test_zero_budget_means_unlimited(self):
        port = _StubPort(
            config=WorkspaceAIConfig(
                workspace_daily_message_budget=0,
                monthly_token_budget=0,
            ),
            workspace_messages_today=999_999,
            workspace_tokens_this_month=999_999_999,
        )
        snapshot = build_workspace_ai_quota_snapshot("ws-1", ai_config_port=port)
        assert snapshot["daily_messages_remaining"] == -1
        assert snapshot["monthly_tokens_remaining"] == -1

    def test_ai_disabled_still_returns_snapshot(self):
        # ai_enabled=False is a workspace-owner toggle, not a quota
        # signal — the frontend uses it to show a "AI is off" banner.
        # The snapshot still surfaces it so the FE can render both
        # states from one payload.
        port = _StubPort(
            config=WorkspaceAIConfig(ai_enabled=False),
        )
        snapshot = build_workspace_ai_quota_snapshot("ws-1", ai_config_port=port)
        assert snapshot["ai_enabled"] is False
