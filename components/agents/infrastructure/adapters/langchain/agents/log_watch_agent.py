"""Log-Watch Agent — the interactive query surface for the ingested log stream.

The SOC log pipeline has three cleanly separated stages:

1. **Detection** — ``LogWatchErrorDetector`` (detector registry) scans the
   ingested stream deterministically (never an LLM over the raw firehose, per
   the POC rule) and files evidence-bearing findings via the ``AIActionCreated``
   path (``persist_finding_as_task``), never a direct ``Task.objects.create``.
2. **Triage** — the triage agent, dispatched by the detector cycle, attaches the
   grounded fix, comments, and moves the card into the Triage column.
3. **This agent** — the on-demand, operator-facing surface: surface recent
   findings and propose a fix for a specific error line. It does NOT file
   findings (that would bypass the AIAction path — §5.7). The former
   ``record_log_finding`` tool (direct create_task) was removed for that reason.

Auto-discovered (ADR 0003). Uses ``self.parse_tool_input`` (BaseAgent helper).
"""

from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)


@register_agent(
    "log_watch_agent",
    aliases=("log_watch", "logwatch", "log_monitor"),
)
class LogWatchAgent(WorkspaceContextMixin, BaseAgent):
    """Turns detected log errors into triaged, human-readable SOC findings."""

    profile = {
        "name": "Log-Watch Agent",
        "summary": (
            "Interactive surface for the ingested log stream from connected AWS "
            "sources. Surfaces recent errors and proposes a grounded fix for a "
            "specific error line on demand. Deterministic detection + finding "
            "filing run upstream in the LogWatchErrorDetector (the AIActionCreated "
            "path); triage into the board is the triage agent's job."
        ),
        "capabilities": [
            "Surface recent log-watch findings on the SOC board",
            "Suggest a grounded fix for a specific detected error",
        ],
        "sample_prompts": [
            "Suggest a fix for this ImportError in celery_worker",
            "What errors has log-watch seen recently?",
        ],
    }

    # NOTE: this agent does NOT file findings. Detection is the
    # ``LogWatchErrorDetector``'s job and flows through the ``AIActionCreated``
    # path (persist_finding_as_task) — never a direct ``Task.objects.create``
    # from agent code (§5.7). The former ``record_log_finding`` tool (direct
    # create_task) was removed for exactly that reason.

    @tool(
        name="suggest_fix",
        description=(
            "Propose a grounded remediation for a single detected log error, "
            "WITHOUT filing a finding. Input: JSON with `message` (the error "
            "line / traceback excerpt), optional `service` and `level`. Returns "
            "a likely root cause + a concrete fix step + a confidence level. Use "
            "when the operator asks 'how do I fix this?' about a specific error."
        ),
    )
    def suggest_fix(self, input_str: str) -> str:
        from components.integrations.application.log_fix_advisor_service import LogFixAdvisor

        data = self.parse_tool_input(input_str, text_key="message")
        message = (data.get("message") or data.get("summary") or "").strip()
        if not message:
            return "message is required to suggest a fix."
        service = (data.get("service") or "unknown").strip()
        level = (data.get("level") or "ERROR").strip()
        suggestion = LogFixAdvisor().suggest(service=service, level=level, message=message)
        if suggestion is None:
            return "Unable to generate a suggestion for this error (LLM unavailable or line insufficient)."
        return (
            f"Likely cause: {suggestion.likely_cause}\n"
            f"Suggested fix: {suggestion.suggested_fix}\n"
            f"Confidence: {suggestion.confidence}"
        )

    @tool(
        name="list_recent_log_findings",
        description="List findings already filed on the SOC board (avoid duplicates before filing).",
    )
    def list_recent_log_findings(self, input_str: str = "") -> str:
        return task_tools.list_workspace_tasks(self, input_str)
