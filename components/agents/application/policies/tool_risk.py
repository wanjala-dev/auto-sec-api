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
#
# Every key MUST name a tool some registered agent actually exposes. Eight keys
# here named nonprofit tools this fork deleted — ``manage_sponsorship_payments``,
# ``cancel_sponsorship``, ``cancel_recurring_donation``, ``send_sponsor_update``,
# ``delete_transaction``, ``delete_news_article``, ``delete_event``,
# ``delete_estimate`` — and survived because nothing checked (ADR 0031 F6, Phase
# 0). A map that is 80% fiction is a map nobody trusts, and an untrusted risk map
# is one nobody notices a real gap in. ``tests/architecture/test_tool_risk_map_is_live.py``
# now fails on the next dead key.
#
# ADR 0031 Phase 4 gave both of these tools a `@tool(risk=...)` declaration too,
# stating the same tier. That looks like the duplication `dry-reuse.md` forbids,
# and these keys stay anyway, for a reason worth writing down: **`tool_observation`
# rows persist the tier as it was resolved at call time, and historical rows carry
# `risk: null`.** `compute_ai_activity` re-resolves those through this map (see
# `test_ai_governance_service.py::test_missing_risk_falls_back_to_central_registry`).
# Empty the map and every `delete_task` call already in the database
# retroactively reports as a `read` — a governance answer that changes because
# the code moved is exactly the kind this module exists to prevent.
#
# So the map is not a second source of truth for *new* calls — `resolve_tool_risk`
# gives the decorator precedence — it is the decoder for *old* ones. It should be
# emptied only alongside a backfill of the rows that depend on it.
_TOOL_RISK: dict[str, str] = {
    # Recoverable soft-deletes (recycle bin) — reversible; documentary only, no
    # approval gate, but named so the classification is explicit not accidental.
    # Both also declare the same tier on their `@tool` decorator (Phase 4).
    "delete_task": ToolRisk.REVERSIBLE_WRITE,
    "delete_project_milestone": ToolRisk.REVERSIBLE_WRITE,
}


def resolve_tool_risk(tool_name: str | None, explicit_risk: str | None = None) -> str:
    """Resolve a tool's tier: explicit ``@tool(risk=...)`` wins, else the central
    registry, else the ``read`` default."""
    if explicit_risk in ToolRisk.ALL:
        return explicit_risk
    return _TOOL_RISK.get(tool_name or "", ToolRisk.READ)


# ── Evaluation isolation (ADR 0033 D5) ──────────────────────────────────────
#
# An eval run executes a real agent against real cases. For the triage agent
# that means an agent which can, in normal operation, open draft PRs on a
# customer's repository, write findings and move board cards. An eval run must
# do none of it: the whole point is to measure judgement, and a harness that
# writes to a customer's repo is worse than no harness.
#
# This gate is SEPARATE from ``tool_risk_refusal`` on purpose, because it needs
# something that function does not have: the tool's NAME, so it can tell a
# DECLARED read from an UNDECLARED tool.
#
# That distinction is the whole design. ``resolve_tool_risk`` returns ``read``
# for both — deliberately, since defaulting to the least-privileged tier is
# right for the autonomy cap. For evaluation it is exactly backwards: a tool
# nobody classified is a tool nobody has checked, and treating it as harmless
# is how a write slips through. So evaluation fails CLOSED — declared-read
# runs, everything else is refused, including anything undeclared.


#: The value ``agent.config["execution_mode"]`` carries during an eval run.
#: Named here, beside the gate that acts on it, so the runner and the enforcer
#: cannot drift apart on a string literal.
EVALUATION_EXECUTION_MODE = "evaluation"


def is_risk_declared(tool_name: str | None, explicit_risk: str | None = None) -> bool:
    """Whether this tool's tier was stated, rather than defaulted.

    A tool is declared when it carries ``@tool(risk=...)`` or appears in the
    central map. Absence is not evidence of harmlessness.
    """
    if explicit_risk in ToolRisk.ALL:
        return True
    return (tool_name or "") in _TOOL_RISK


def evaluation_may_execute(tool_name: str | None, explicit_risk: str | None = None) -> bool:
    """True only for a tool explicitly declared ``read``."""
    return is_risk_declared(tool_name, explicit_risk) and resolve_tool_risk(tool_name, explicit_risk) == ToolRisk.READ


def evaluation_refusal(tool_name: str | None, explicit_risk: str | None = None) -> str | None:
    """Refusal message for a tool an evaluation run must not execute.

    Returns ``None`` when the tool is cleared. Two refusals, deliberately
    worded differently, because they need different fixes: a write tool is
    working as intended and simply has no place in an eval run, while an
    undeclared tool is a gap in the contract that someone must close.
    """
    if evaluation_may_execute(tool_name, explicit_risk):
        return None

    if not is_risk_declared(tool_name, explicit_risk):
        return (
            f"Evaluation runs refuse undeclared tools. '{tool_name or 'unnamed'}' has no "
            "risk tier on its @tool decorator or in the central map, so it cannot be "
            "shown to be read-only. Declare its tier, then re-run."
        )

    return (
        f"Evaluation runs are read-only. '{tool_name or 'unnamed'}' changes state "
        f"({resolve_tool_risk(tool_name, explicit_risk)}), and an eval must measure "
        "judgement without altering the workspace it is measuring. Report what you "
        "WOULD have done instead."
    )
