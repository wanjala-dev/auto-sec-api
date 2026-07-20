"""Unit tests for the LogAnalyticsAgent (AgentTestCase harness — no real LLM).

The query services are mocked at the application-service import
(``tools.log_analytics_agent.metrics_query``), so these tests prove the tool
layer's contract: registration, arg parsing, honest summaries built ONLY from
service numbers, and friendly (non-raising) error shapes.
"""

from __future__ import annotations

from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.agents.log_analytics_agent import (
    LogAnalyticsAgent,
)
from components.agents.infrastructure.adapters.langchain.base import ToolResult
from components.agents.infrastructure.adapters.langchain.tools import (
    log_analytics_agent as analytics_tools,
)
from components.agents.tests.agent_test_case import AgentTestCase

_TOOLS = "components.agents.infrastructure.adapters.langchain.tools.log_analytics_agent"


class LogAnalyticsAgentToolRegistrationTests(AgentTestCase):
    def test_all_four_tools_registered(self):
        agent = self.make_agent(LogAnalyticsAgent)
        tool_names = {t.name for t in agent.tools}
        assert {
            "query_log_metric",
            "get_metric_trend",
            "get_top_sources",
            "list_available_metrics",
        } <= tool_names

    def test_workspace_context_mixin_tools_present(self):
        agent = self.make_agent(LogAnalyticsAgent)
        tool_names = {t.name for t in agent.tools}
        assert {"whoami", "get_workspace_info"} <= tool_names


class QueryLogMetricToolTests(AgentTestCase):
    def _invoke(self, agent, input_str):
        return agent.agent_executor.invoke({"input": input_str})

    def test_happy_path_counts_from_service(self):
        agent = self.make_agent(LogAnalyticsAgent, workspace_id="11111111-1111-1111-1111-111111111111")
        with patch(
            f"{_TOOLS}.metrics_query.query_metric",
            return_value={
                "metric": "auth_failure",
                "window_hours": 168,
                "total": 42,
                "group_by": None,
                "rows": [],
            },
        ) as mocked:
            result = analytics_tools.query_log_metric(agent, '{"metric": "ssh", "window": "7d"}')

        assert isinstance(result, ToolResult)
        assert result.ok
        assert "42 auth_failure event(s)" in result.message
        assert result.data["total"] == 42
        mocked.assert_called_once_with(agent.workspace_id, "ssh", window_hours=168, group_by=None)

    def test_zero_total_reports_no_data_honestly(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.query_metric",
            return_value={"metric": "sqli_signature", "window_hours": 720, "total": 0, "group_by": None, "rows": []},
        ):
            result = analytics_tools.query_log_metric(agent, '{"metric": "sqli", "window": "month"}')
        assert result.ok
        assert "No sqli_signature data in window" in result.message

    def test_missing_metric_is_friendly_error(self):
        agent = self.make_agent(LogAnalyticsAgent)
        result = analytics_tools.query_log_metric(agent, "")
        assert isinstance(result, ToolResult)
        assert not result.ok
        assert "auth_failure" in result.error  # taxonomy listed

    def test_unknown_metric_valueerror_surfaces_message(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.query_metric",
            side_effect=ValueError("Unknown metric 'bananas'. Valid metrics: auth_failure, …"),
        ):
            result = analytics_tools.query_log_metric(agent, '{"metric": "bananas"}')
        assert not result.ok
        assert "Unknown metric" in result.error

    def test_unexpected_exception_does_not_raise(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(f"{_TOOLS}.metrics_query.query_metric", side_effect=RuntimeError("db down")):
            result = analytics_tools.query_log_metric(agent, '{"metric": "ssh"}')
        assert not result.ok
        assert "failed" in result.error.lower()

    def test_bad_window_is_friendly_error(self):
        agent = self.make_agent(LogAnalyticsAgent)
        result = analytics_tools.query_log_metric(agent, '{"metric": "ssh", "window": "fortnight-ish"}')
        assert not result.ok
        assert "window" in result.error.lower()

    def test_bare_metric_string_input_accepted(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.query_metric",
            return_value={"metric": "app_error", "window_hours": 168, "total": 7, "group_by": None, "rows": []},
        ) as mocked:
            result = analytics_tools.query_log_metric(agent, "errors")
        assert result.ok
        assert mocked.call_args.args[1] == "errors"


class MetricTrendToolTests(AgentTestCase):
    def test_spike_summary_carries_the_evidence_numbers(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.classify_trend",
            return_value={
                "metric": "total_volume",
                "window_hours": 720,
                "pattern": "spike",
                "total": 5000,
                "active_hours": 3,
                "max_hour_count": 4800,
                "median_hourly": 2,
                "active_share": 0.004,
            },
        ):
            result = analytics_tools.get_metric_trend(agent, '{"metric": "total_volume", "window": "month"}')
        assert result.ok
        assert "pattern=spike" in result.message
        assert "peak hour=4800" in result.message
        assert result.data["pattern"] == "spike"

    def test_defaults_to_total_volume_when_metric_omitted(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.classify_trend",
            return_value={
                "metric": "total_volume",
                "window_hours": 168,
                "pattern": "quiet",
                "total": 0,
                "active_hours": 0,
                "max_hour_count": 0,
                "median_hourly": 0,
                "active_share": 0.0,
            },
        ) as mocked:
            result = analytics_tools.get_metric_trend(agent, "")
        assert result.ok
        assert "No total_volume data in window" in result.message
        assert mocked.call_args.args[1] == "total_volume"


class TopSourcesToolTests(AgentTestCase):
    def test_top_sources_listed_with_counts(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.top_sources",
            return_value={
                "metric": "auth_failure",
                "window_hours": 168,
                "total": 40,
                "sources": [
                    {"source": "203.0.113.9", "count": 30},
                    {"source": "198.51.100.7", "count": 10},
                ],
            },
        ):
            result = analytics_tools.get_top_sources(agent, '{"metric": "ssh", "window": "week"}')
        assert result.ok
        assert "203.0.113.9 (30)" in result.message
        assert result.data["sources"][0]["count"] == 30

    def test_no_sources_reported_honestly(self):
        agent = self.make_agent(LogAnalyticsAgent)
        with patch(
            f"{_TOOLS}.metrics_query.top_sources",
            return_value={"metric": "scanner", "window_hours": 168, "total": 0, "sources": []},
        ):
            result = analytics_tools.get_top_sources(agent, '{"metric": "scanner"}')
        assert result.ok
        assert "No scanner events with a derivable source IP" in result.message

    def test_missing_metric_is_friendly_error(self):
        agent = self.make_agent(LogAnalyticsAgent)
        result = analytics_tools.get_top_sources(agent, "{}")
        assert not result.ok


class ListAvailableMetricsToolTests(AgentTestCase):
    def test_taxonomy_listed(self):
        agent = self.make_agent(LogAnalyticsAgent)
        result = analytics_tools.list_available_metrics(agent)
        assert result.ok
        metrics = result.data["metrics"]
        assert set(metrics) == {
            "auth_failure",
            "http_5xx",
            "http_4xx",
            "sqli_signature",
            "scanner",
            "app_error",
            "app_warning",
            "total_volume",
        }


class ScriptedExecutorSmokeTests(AgentTestCase):
    """One end-to-end pass through the harness executor, per the README."""

    def test_llm_choosing_query_tool_reaches_the_service_summary(self):
        self.mock_tool_returns(
            "query_log_metric",
            ToolResult(message="42 auth_failure event(s) in the last 7 day(s)."),
        )
        self.mock_llm_chooses("query_log_metric", '{"metric": "ssh", "window": "7d"}')
        agent = self.make_agent(LogAnalyticsAgent)

        result = agent.agent_executor.invoke({"input": "how many ssh attempts this week?"})

        self.assert_tool_called("query_log_metric")
        assert "42 auth_failure" in result["output"]
