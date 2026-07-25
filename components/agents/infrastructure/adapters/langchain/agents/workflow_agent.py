"""Workflow Agent — drafts SOC automation playbooks from a description.

Turns a natural-language request ("when a critical finding lands, alert the SOC
and run the AI triage agent") into a workflow graph and saves it as a DRAFT the
operator opens in the Workflow Builder to review, tweak, and publish. It never
publishes or fires anything — AI proposes, the human disposes.

Reuses the workflow context's ``DraftWorkflowGraphUseCase`` (constrained to the
real node/trigger catalog and validate-and-repaired against the publish gate)
and persists through ``WorkflowService`` — cross-context APPLICATION imports
only, which the architecture manifesto allows; it never touches another
context's domain or infrastructure layer.

Auto-discovered (ADR 0003) — no edits to base.py or the registry; the AgentType
row syncs from this ``@register_agent`` + ``profile``.
"""

import json
import logging

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)

logger = logging.getLogger(__name__)


def _parse_input(input_str: str) -> str:
    """Accept the request as plain text or JSON ``{"description": "..."}``."""
    raw = (input_str or "").strip()
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return str(data.get("description") or data.get("prompt") or data.get("value") or "").strip()
        except (ValueError, TypeError):
            return raw
    return raw


@register_agent(
    "workflow_agent",
    aliases=("workflow", "workflows", "playbook", "playbooks", "automation"),
)
class WorkflowAgent(WorkspaceContextMixin, BaseAgent):
    """Drafts SOC automation workflows (playbooks) from a natural-language request."""

    profile = {
        "name": "Workflow Agent",
        "summary": (
            "Creates SOC automation workflows (playbooks) from a natural-language "
            "description — 'when X happens, do Y'. It drafts the workflow graph "
            "(trigger → steps → branches, over the real node + trigger catalog: "
            "finding triggers, in-app/Slack/email messages, the AI triage agent, "
            "severity conditions, SOAR webhooks, waits), validates it against the "
            "publish gate (repairing until it passes), and saves it as a DRAFT in "
            "the workspace for an operator to open in the Workflow Builder, review, "
            "tweak, and publish. It proposes; the human disposes — it never "
            "publishes a workflow or fires an action itself."
        ),
        "capabilities": [
            "Draft a workflow / playbook from a plain-English description of a trigger and steps",
            "Ground the graph in the real node + trigger catalog and validate it against the publish gate",
            "Save the result as a reviewable draft and point the user to the Workflow Builder",
        ],
        "sample_prompts": [
            "Create a workflow that alerts the SOC and runs AI triage when a critical finding lands",
            "Build a playbook: on high or critical findings, forward to our SOAR webhook, otherwise log it",
            "Automate triage for new high-severity findings and notify the team on Slack",
        ],
    }

    @tool(
        name="draft_workflow",
        description=(
            "Draft a SOC automation workflow (playbook) from a natural-language "
            "description and save it as a DRAFT. Input: the automation in plain "
            'English (or JSON {"description": "..."}), e.g. "when a critical '
            "finding lands, alert the SOC in-app and then run the AI triage "
            'agent". Drafts the workflow graph over the real node + trigger '
            "catalog, validates it against the publish gate, saves it as a draft "
            "in this workspace, and returns the steps plus where to open it. It "
            "never publishes the workflow or fires any action — a human reviews "
            "and publishes it in the Workflow Builder."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def draft_workflow(self, input_str: str = "") -> str:
        # Cross-context APPLICATION imports only (allowed): the draft use case
        # owns the LLM + validate-and-repair loop; the service owns persistence.
        from components.workflow.application.providers.workflow_draft_provider import (
            WorkflowDraftProvider,
        )
        from components.workflow.application.service import WorkflowService

        description = _parse_input(input_str)
        if not description:
            return (
                "Describe the automation and I'll draft it — name the trigger and the steps, "
                "e.g. 'when a critical finding lands, alert the SOC and run the AI triage agent'."
            )

        use_case = WorkflowDraftProvider.build_draft_use_case()
        if not use_case.is_available():
            return "AI workflow drafting is not configured in this environment yet."

        result = use_case.execute(prompt=description, workspace_id=str(self.workspace_id))
        graph = result.get("graph") or {}
        nodes = graph.get("nodes") or []
        if not nodes:
            return (
                "I couldn't draft a workflow from that. Try naming the trigger "
                "(e.g. 'a critical finding') and the steps to run."
            )

        steps = [str(n.get("label") or n.get("type") or "step") for n in nodes]

        try:
            workflow = WorkflowService().create_workflow(
                workspace_id=str(self.workspace_id),
                name=result.get("name") or "AI-drafted workflow",
                goal=result.get("goal") or "security",
                graph=graph,
                status="draft",
                is_custom=True,
                created_by=self._resolve_user(),
            )
        except Exception:
            logger.exception("workflow_agent.create_failed workspace_id=%s", self.workspace_id)
            # The draft is still useful — hand back the steps for the operator to
            # rebuild in the builder, rather than swallowing the work.
            return json.dumps(
                {
                    "status": "drafted_not_saved",
                    "name": result.get("name"),
                    "valid": result.get("valid"),
                    "steps": steps,
                    "message": (
                        "I drafted the workflow but couldn't save it. Open the Workflow "
                        "Builder and use AI Assist to regenerate it."
                    ),
                }
            )

        workflow_id = getattr(workflow, "id", None)
        logger.info(
            "workflow_agent.drafted workflow_id=%s workspace_id=%s valid=%s steps=%s",
            workflow_id,
            self.workspace_id,
            result.get("valid"),
            len(steps),
        )
        publish_note = (
            ""
            if result.get("valid")
            else " It still needs a couple of fixes before it can publish — the builder will flag them."
        )
        return json.dumps(
            {
                "workflow_id": str(workflow_id) if workflow_id else None,
                "name": result.get("name"),
                "status": "draft",
                "valid": result.get("valid"),
                "steps": steps,
                "message": (
                    "Saved as a draft in this workspace. Open it in the Workflow Builder "
                    "(Workflows → Edit) to review, tweak, and Publish — nothing runs until "
                    "you publish it." + publish_note
                ),
            }
        )

    def _resolve_user(self):
        """The requesting user, to attribute the draft's ``created_by`` (or None)."""
        user_id = getattr(self, "user_id", None)
        if not user_id:
            return None
        try:
            from infrastructure.persistence.users.models import CustomUser

            return CustomUser.objects.filter(id=user_id).first()
        except Exception:
            logger.exception("workflow_agent.resolve_user_failed user_id=%s", user_id)
            return None

    # The specialist drafting discipline lives in the registry at
    # ``prompts/data/workflow_agent.system.yaml`` and is auto-appended by
    # ``BaseAgent._build_system_message`` via the ``<agent_slug>.system``
    # convention — so it is versioned, hygiene-tested, and rollback-able, with no
    # ``_build_system_message`` override here.
