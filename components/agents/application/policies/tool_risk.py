"""SEE-203 — per-tool risk tiers + the approval/autonomy policy.

Every agent tool carries a risk tier. The tier drives two orthogonal gates that
compose with ``@requires_role`` (role, never persona) and the autonomous-principal
cap (SEE-201):

- **Autonomy cap** — an autonomous run (the scheduled detector) may execute
  ``read`` and ``reversible_write`` tools but never an ``irreversible`` one; it
  surfaces a finding for a human instead.
- **Human approval** — an ``irreversible`` tool (money movement, cancellation,
  deletion, external send) runs only when a human has approved this run.

Tiers, least → most dangerous:
- ``read``            — no state change (list/get/analyse). The default.
- ``reversible_write``— creates/edits recoverable state (draft, task, note).
- ``irreversible``    — money movement or a hard-to-undo/external effect.

Classifying a new tool: default to ``read``; raise the tier only for what the
tool actually does. Under-classifying an irreversible money tool as ``read`` is
the failure this module exists to prevent — when in doubt, classify UP.
"""

from __future__ import annotations


class ToolRisk:
    READ = "read"
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE = "irreversible"

    ALL = (READ, REVERSIBLE_WRITE, IRREVERSIBLE)


#: Tiers an autonomous run may execute. ``irreversible`` is intentionally absent.
_AUTONOMOUS_ALLOWED = frozenset({ToolRisk.READ, ToolRisk.REVERSIBLE_WRITE})


def normalize_risk(risk: str | None) -> str:
    """Coerce an unknown/blank tier to the safe default (``read``)."""
    return risk if risk in ToolRisk.ALL else ToolRisk.READ


def autonomous_may_execute(risk: str | None) -> bool:
    """True when an autonomous run may execute a tool of this tier."""
    return normalize_risk(risk) in _AUTONOMOUS_ALLOWED


def requires_human_approval(risk: str | None) -> bool:
    """True when a tool of this tier needs explicit human approval to run."""
    return normalize_risk(risk) == ToolRisk.IRREVERSIBLE


def tool_risk_refusal(risk: str | None, *, is_autonomous: bool, approval_granted: bool) -> str | None:
    """Return a refusal message if a tool of *risk* must not run in this context.

    Returns ``None`` when the tool is cleared to run. The autonomy cap is checked
    first: an autonomous run never reaches the approval branch for an
    irreversible tool — it is denied outright and expected to raise a finding.
    """
    normalized = normalize_risk(risk)
    if is_autonomous and not autonomous_may_execute(normalized):
        return (
            "Autonomous AI runs cannot perform this irreversible action. "
            "Surface it as a finding for a human to review and approve."
        )
    if requires_human_approval(normalized) and not approval_granted:
        return (
            "This action is irreversible and needs human approval before it "
            "runs. Ask the user to confirm, then retry once approved."
        )
    return None


# Central classification of the existing tools by name. New tools set their tier
# on the ``@tool(risk=...)`` decorator (which takes precedence); this map keeps
# one auditable list for the tools that predate the decorator arg. Only tiers
# above the default (``read``) are listed.
_TOOL_RISK: dict[str, str] = {
    # Money movement / external send / financial-record deletion — approval-gated
    # and denied to autonomous runs.
    "manage_sponsorship_payments": ToolRisk.IRREVERSIBLE,
    "cancel_sponsorship": ToolRisk.IRREVERSIBLE,
    "cancel_recurring_donation": ToolRisk.IRREVERSIBLE,
    "send_sponsor_update": ToolRisk.IRREVERSIBLE,
    "delete_transaction": ToolRisk.IRREVERSIBLE,
    # Recoverable soft-deletes (recycle bin) — reversible; documentary only, no
    # approval gate, but named so the classification is explicit not accidental.
    "delete_task": ToolRisk.REVERSIBLE_WRITE,
    "delete_project_milestone": ToolRisk.REVERSIBLE_WRITE,
    "delete_news_article": ToolRisk.REVERSIBLE_WRITE,
    "delete_event": ToolRisk.REVERSIBLE_WRITE,
    "delete_estimate": ToolRisk.REVERSIBLE_WRITE,
}


def resolve_tool_risk(tool_name: str | None, explicit_risk: str | None = None) -> str:
    """Resolve a tool's tier: explicit ``@tool(risk=...)`` wins, else the central
    registry, else the ``read`` default."""
    if explicit_risk in ToolRisk.ALL:
        return explicit_risk
    return _TOOL_RISK.get(tool_name or "", ToolRisk.READ)
