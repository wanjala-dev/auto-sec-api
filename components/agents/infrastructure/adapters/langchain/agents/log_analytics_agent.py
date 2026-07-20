"""Log Analytics Agent — "chat with the logs" over deterministic aggregates.

Answers quantitative questions about the ingested log stream: "how many SSH
attempts this week?", "5xx this month — spike or sustained? DDoS?", "where
did the attacks come from?", "how many SQL injections?", "app errors by
service".

**Routing rule (posture vision §3.2, the aggregation-first rule): counting
and trend questions route HERE, never to RAG.** Every number this agent
reports comes from ORM aggregates over hourly ``LogMetricBucket`` rows that
the deterministic ingest classifier wrote — no LLM ever computes or writes
an aggregate, and this agent may only narrate the tool output. Narrative /
docs questions belong to RAG; discrete error triage belongs to
``log_watch_agent``/``triage_agent``; recurring-pattern tuning belongs to
``optimization_agent``.

Auto-discovered (ADR 0003) — no edits to base.py or the registry.
"""

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    log_analytics_agent as analytics_tools,
)


@register_agent(
    "log_analytics_agent",
    aliases=("log_analytics", "log_metrics", "log_stats", "log_query"),
)
class LogAnalyticsAgent(WorkspaceContextMixin, BaseAgent):
    """Answers counting and trend questions about the logs from deterministic
    hourly security-metric aggregates — never RAG, never invented numbers."""

    profile = {
        "name": "Log Analytics Agent",
        "summary": (
            "Answers quantitative log questions — how many SSH/auth attempts, "
            "HTTP 5xx/4xx, SQL injections, scanner probes, app errors — plus "
            "spike-vs-sustained trend calls (was that a DDoS?) and top attack "
            "sources, from deterministic hourly security-metric aggregates. "
            "Always states the exact counts and the window measured; says "
            "'no data in window' honestly when the buckets are empty."
        ),
        "capabilities": [
            "Count a security metric over a window (SSH attempts, 5xx, SQLi, scanners, errors)",
            "Group counts by service, source IP, day, or hour",
            "Classify a metric's trend as spike, sustained, or quiet (DDoS-shaped questions)",
            "Rank the top attack source IPs for a metric",
            "List the available security-metric taxonomy",
        ],
        "sample_prompts": [
            "How many SSH attempts did we have this week?",
            "Did we get DDoSed this month?",
            "Where did the attacks come from?",
            "App errors by service over the last 7 days",
        ],
    }

    @tool(
        name="query_log_metric",
        description=(
            "Count one security metric over a time window, optionally grouped. "
            'Input JSON: {"metric": "auth_failure|http_5xx|http_4xx|'
            'sqli_signature|scanner|app_error|app_warning|total_volume", '
            '"window": "24h|7d|30d|week|month", "group_by": '
            '"service|source|day|hour" (optional)}. Friendly metric names '
            "(ssh, 5xx, sqli, errors) are accepted. Returns the exact total "
            "plus grouped rows. Use for any 'how many …' question."
        ),
        risk=ToolRisk.READ,
    )
    def query_log_metric(self, input_str: str = ""):
        return analytics_tools.query_log_metric(self, input_str)

    @tool(
        name="get_metric_trend",
        description=(
            "Classify a metric's hourly shape over a window as spike | "
            "sustained | quiet, with the measured evidence (peak hour, median "
            'hourly, active-hour share). Input JSON: {"metric": "<metric>", '
            '"window": "7d|30d|…"}. Use for "did we get DDoSed?", "is this a '
            'spike or sustained?" questions (default metric: total_volume).'
        ),
        risk=ToolRisk.READ,
    )
    def get_metric_trend(self, input_str: str = ""):
        return analytics_tools.get_metric_trend(self, input_str)

    @tool(
        name="get_top_sources",
        description=(
            "Rank the top source IPs for an attack-shaped metric over a "
            'window — "where did the attacks come from". Input JSON: '
            '{"metric": "auth_failure|scanner|sqli_signature|http_4xx|'
            'http_5xx", "window": "7d|30d|…", "limit": 10}. Returns source '
            "IPs with exact counts."
        ),
        risk=ToolRisk.READ,
    )
    def get_top_sources(self, input_str: str = ""):
        return analytics_tools.get_top_sources(self, input_str)

    @tool(
        name="list_available_metrics",
        description=(
            "List the security-metric taxonomy this agent can answer about, "
            "with a description of each metric. No input. Call this when the "
            "user's question doesn't obviously map to a metric."
        ),
        risk=ToolRisk.READ,
    )
    def list_available_metrics(self, input_str: str = ""):
        return analytics_tools.list_available_metrics(self, input_str)
