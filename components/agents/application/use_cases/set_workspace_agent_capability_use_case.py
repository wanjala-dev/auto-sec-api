"""Workspace-level owner toggle for a gated triage-agent capability.

The last mile of the ADR 0010 draft-PR loop. ``OpenDraftPrUseCase`` reads the
workspace's ``triage_agent`` row and refuses unless
``config.capabilities.open_draft_pr is True`` — but nothing could set that flag.
This use case is the setter: an owner enabling/disabling a capability at the
workspace level, co-located (in the API) with the VcsConnection consent boundary.

It is deliberately WORKSPACE-level, not agent-id level (the per-agent surface
already exists at ``AgentsService.patch_agent_capabilities``): the operator's
mental model is "may this workspace's triage agent open draft PRs?", and a fresh
org has no ``triage_agent`` row yet — so this ENSURES one (get-or-create) rather
than 404-ing, and the toggle works on day one.

Same governance discipline as the AI kill switch (``SetAiKillSwitchUseCase``):
owner-gated at the endpoint, allowlisted keys only, value coerced to bool, and an
immutable audit row (who granted what, when) through the audit context's
application provider. Read side: ``get_workspace_capabilities``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from components.agents.application.config.agent_capabilities import (
    ALLOWED_AGENT_CAPABILITIES,
    TRIAGE_AGENT_TYPE,
)
from components.shared_kernel.domain.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceAgentCapabilityResult:
    """Current capability state for the workspace's triage agent.

    ``created`` is True when this call had to create the ``triage_agent`` row
    (fresh workspace) — surfaced so the caller/log can tell an ensure from a
    plain toggle.
    """

    workspace_id: str
    agent_type: str = TRIAGE_AGENT_TYPE
    capabilities: dict[str, bool] = field(default_factory=dict)
    created: bool = False


class SetWorkspaceAgentCapabilityUseCase:
    """Enable/disable one gated capability on the workspace's triage agent."""

    def execute(
        self,
        *,
        workspace_id: str,
        capability: str,
        enabled: bool,
        actor: Any,
    ) -> WorkspaceAgentCapabilityResult:
        from infrastructure.persistence.ai.agents.models import Agent
        from infrastructure.persistence.workspaces.models import Workspace

        capability = (capability or "").strip()
        if capability not in ALLOWED_AGENT_CAPABILITIES:
            raise ValidationError(
                f"Unknown capability '{capability}'. Allowed: {', '.join(sorted(ALLOWED_AGENT_CAPABILITIES))}."
            )
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be a boolean.")

        workspace = Workspace.objects.filter(id=str(workspace_id)).first()
        if workspace is None:
            raise NotFoundError(f"Workspace {workspace_id} not found")

        agent, created = self._ensure_triage_agent(Agent, workspace, actor)

        previous_capabilities = dict(agent.config.get("capabilities") or {})
        capabilities = dict(previous_capabilities)
        capabilities[capability] = enabled

        merged_config = dict(agent.config or {})
        merged_config["capabilities"] = capabilities
        agent.config = merged_config
        agent.save(update_fields=["config", "updated_at"])

        self._audit(agent, previous_capabilities, capabilities, actor)

        logger.info(
            "workspace_agent_capability_set workspace_id=%s capability=%s enabled=%s created=%s actor_id=%s",
            workspace_id,
            capability,
            enabled,
            created,
            getattr(actor, "id", None),
        )
        return WorkspaceAgentCapabilityResult(
            workspace_id=str(workspace_id),
            capabilities={key: bool(value) for key, value in capabilities.items()},
            created=created,
        )

    @staticmethod
    def _ensure_triage_agent(Agent, workspace, actor):
        """Return the workspace's most-recent triage_agent row, creating one if
        the workspace has none yet (fresh org). Create-if-missing mirrors the
        row-resolution ``OpenDraftPrUseCase._require_capability`` reads
        (``order_by('-created_at').first()``), so the row this touches is the
        same row the gate consults."""
        agent = Agent.objects.filter(workspace=workspace, agent_type=TRIAGE_AGENT_TYPE).order_by("-created_at").first()
        if agent is not None:
            if not isinstance(agent.config, dict):
                agent.config = {}
            return agent, False

        # No triage agent yet — provision one so the capability has a row to
        # live on. ``Agent.user`` is non-null; the workspace owner is the
        # natural owner of a workspace-level grant, falling back to the acting
        # owner (the endpoint is owner-gated, so ``actor`` IS the owner).
        owner = getattr(workspace, "workspace_owner", None) or actor
        agent = Agent.objects.create(
            workspace=workspace,
            user=owner,
            agent_type=TRIAGE_AGENT_TYPE,
            config={},
        )
        return agent, True

    @staticmethod
    def _audit(agent, previous_capabilities: dict, capabilities: dict, actor: Any) -> None:
        """Immutable grant record (the audit facade suppresses no-op writes)."""
        try:
            from components.audit.application.providers.audit_log_provider import (
                get_audit_log_provider,
            )

            get_audit_log_provider().log_field_change(
                instance=agent,
                field_name="capabilities",
                previous_value=previous_capabilities,
                new_value=capabilities,
                actor=actor,
                reason="workspace triage-agent capability toggle (owner)",
            )
        except Exception:
            # The flip must not be lost to an audit hiccup, but a silent audit
            # gap is a governance defect — log loudly.
            logger.exception(
                "workspace_agent_capability audit write failed agent_id=%s",
                getattr(agent, "agent_id", None),
            )


def get_workspace_capabilities(workspace_id: str) -> WorkspaceAgentCapabilityResult:
    """Read the current capability state for the workspace's triage agent.

    Read-only: never creates a row. A workspace with no ``triage_agent`` yet
    reports every allowlisted capability as ``False`` (the effective state the
    gate enforces), so the UI renders a consistent "off" without a write.
    """
    from infrastructure.persistence.ai.agents.models import Agent

    agent = (
        Agent.objects.filter(workspace_id=str(workspace_id), agent_type=TRIAGE_AGENT_TYPE)
        .order_by("-created_at")
        .only("agent_id", "config")
        .first()
    )
    stored = {}
    if agent is not None and isinstance(agent.config, dict):
        raw = agent.config.get("capabilities")
        if isinstance(raw, dict):
            stored = raw

    capabilities = {key: bool(stored.get(key)) for key in sorted(ALLOWED_AGENT_CAPABILITIES)}
    return WorkspaceAgentCapabilityResult(workspace_id=str(workspace_id), capabilities=capabilities, created=False)
