"""Log Optimization Agent.

The consumer specialist for the log-optimization pipeline. The
``LogOptimizationDetector`` watches logs OVER TIME (temporal aggregation) and
files evidence-bearing pattern findings — an over-scheduled beat task, health-
check noise, a service dominating volume — targeting this agent. The agent turns
each measured pattern into a concrete tuning recommendation ("raise the interval
from */5 to */15 — ~66% fewer scheduler wakeups"), comments it on the card, and
advances it to the Optimize column.

This exists as a DISTINCT specialist (not folded into triage) to prove the
pipeline scales to new finding KINDS: a new detector emits a new
``action_type`` → new specialist here → the router gains ONE
``ROUTABLE_SOURCE_TYPES`` entry, its dispatch logic untouched. Same
orchestrator-routed path as every other worker.

Auto-discovered (ADR 0003) — no edits to base.py or the registry. Reuses the
shared finding-processing core (concurrency guard + provenance) via its tools.
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
    optimization_agent as optimization_tools,
)


@register_agent(
    "optimization_agent",
    aliases=("optimization", "log_optimization", "log_optimizer"),
)
class OptimizationAgent(WorkspaceContextMixin, BaseAgent):
    """Turns sustained, high-frequency log patterns into tuning recommendations."""

    profile = {
        "name": "Log Optimization Agent",
        "summary": (
            "Reviews recurring log patterns the log-optimization detector has "
            "flagged over time (over-scheduled jobs, health-check noise, volume "
            "hotspots) and recommends concrete resource-saving changes — taking "
            "log noise and wasted compute off the platform team."
        ),
        "capabilities": [
            "List pending log-optimization findings on the board",
            "Turn a measured frequency pattern into a concrete tuning recommendation",
            "Estimate the resource win of a change",
            "Comment the recommendation and advance the card to Optimize",
        ],
        "sample_prompts": [
            "What log-optimization findings are pending?",
            "Advise on the over-scheduled task finding on the board",
            "Review the health-check noise pattern and recommend a fix",
        ],
    }

    @tool(
        name="list_pending_optimizations",
        description=(
            "List log-optimization findings on the board not yet handled. No "
            "input. Returns JSON: [{task_id, title, service, kind, subject, "
            "last_window, signal}]. Call this first, then advise_optimization on each."
        ),
        risk=ToolRisk.READ,
    )
    def list_pending_optimizations(self, input_str: str = "") -> str:
        return optimization_tools.list_pending_optimizations(self, input_str)

    @tool(
        name="advise_optimization",
        description=(
            "Advise one pending log-optimization finding: turn its measured "
            "frequency into a concrete tuning recommendation, post it as a comment, "
            'and move the card to the Optimize column. Input: JSON {"task_id": '
            '"<id>"} (or the bare task_id). Reversible — safe for autonomous runs.'
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def advise_optimization(self, input_str: str) -> str:
        return optimization_tools.advise_optimization(self, input_str)
