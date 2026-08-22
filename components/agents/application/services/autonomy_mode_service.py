"""Read and change a workspace's autonomy mode (ADR 0035 D6/D8).

The write delegates to the ``workspace`` context, which owns the field and
records the audit. Nothing here touches a workspace model.

**The catalog is served, not duplicated in the client.** What each mode permits
is derived from :class:`AutonomyPolicy` — the same object the tool gate enforces
with — rather than written out again in the HUD. A UI that describes a policy
from its own hardcoded copy is one deploy away from describing a policy the
backend no longer applies, and for this particular control that is the kind of
wrong that ends up in a security questionnaire.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.policies.autonomy_policy import AutonomyPolicy, ToolDecision
from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.domain.value_objects.autonomy_mode import AutonomyMode, parse

#: Order shown in the UI: least → most permissive.
_SELECTABLE = (AutonomyMode.MANUAL, AutonomyMode.ASSIST, AutonomyMode.AUTONOMOUS)

_SUMMARIES = {
    AutonomyMode.MANUAL: "Reads and analyses. Proposes every change for you to make.",
    AutonomyMode.ASSIST: "Makes reversible changes itself. Irreversible actions need your approval.",
    AutonomyMode.AUTONOMOUS: "Runs unattended on a schedule. Same limits as Assist — nothing more.",
}

_INITIATED_BY = {
    AutonomyMode.MANUAL: "A human, every run",
    AutonomyMode.ASSIST: "A human or an event",
    AutonomyMode.AUTONOMOUS: "The scheduler, unattended",
}

#: What the UI labels each decision. Kept here so "propose" reads the same on
#: every surface that renders the matrix.
_DECISION_LABELS = {
    ToolDecision.EXECUTE: "runs",
    ToolDecision.HOLD: "proposed",
    ToolDecision.REQUIRE_APPROVAL: "needs approval",
    ToolDecision.DENY: "refused",
}

_RISK_LABELS = (
    (ToolRisk.READ, "Read / analyse"),
    (ToolRisk.REVERSIBLE_WRITE, "Reversible change"),
    (ToolRisk.IRREVERSIBLE, "Irreversible action"),
)


def _permissions_for(mode: AutonomyMode) -> list[dict[str, str]]:
    """What this mode does with each risk tier, asked of the real policy."""
    policy = AutonomyPolicy.for_mode(mode)
    rows = []
    for risk, label in _RISK_LABELS:
        # approval_granted=False is the un-approved baseline — what the mode
        # permits on its own, before a human intervenes. Passing True would
        # describe every mode as permitting everything.
        decision = policy.decide(risk, approval_granted=False)
        rows.append(
            {
                "risk": risk,
                "label": label,
                "decision": decision.value,
                "decision_label": _DECISION_LABELS[decision],
            }
        )
    return rows


def catalog() -> list[dict[str, Any]]:
    """The selectable modes, described by the policy that enforces them."""
    return [
        {
            "mode": mode.value,
            "label": mode.label,
            "summary": _SUMMARIES[mode],
            "initiated_by": _INITIATED_BY[mode],
            "permissions": _permissions_for(mode),
        }
        for mode in _SELECTABLE
    ]


def status(workspace_id: str) -> dict[str, Any]:
    """The workspace's current mode plus the catalog the UI renders."""
    from components.shared_kernel.domain.errors import NotFoundError
    from components.workspace.application.providers.workspace_autonomy_provider import (
        WorkspaceAutonomyProvider,
    )

    stored = WorkspaceAutonomyProvider.build_get_workspace_autonomy_mode_use_case().execute(
        workspace_id=str(workspace_id)
    )
    if stored is None:
        raise NotFoundError(f"Workspace {workspace_id} not found")

    current = parse(stored)
    return {
        "workspace_id": str(workspace_id),
        "mode": current.value,
        "label": current.label,
        # False for a row whose stored value we cannot interpret. The UI shows
        # UNKNOWN rather than pre-selecting a mode nobody chose.
        "is_recorded": current.is_recorded,
        "modes": catalog(),
    }


def set_mode(*, workspace_id: str, mode: str, actor: Any, reason: str) -> dict[str, Any]:
    """Change the mode through the owning context, then report the new state."""
    from components.workspace.application.providers.workspace_autonomy_provider import (
        WorkspaceAutonomyProvider,
    )

    result = WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case().execute(
        workspace_id=str(workspace_id), mode=mode, actor=actor, reason=reason
    )
    payload = status(str(workspace_id))
    payload["previous"] = result.previous
    payload["changed"] = result.changed
    return payload
