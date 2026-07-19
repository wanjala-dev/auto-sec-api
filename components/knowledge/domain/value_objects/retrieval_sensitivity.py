"""Retrieval sensitivity tiers — role-scoped RAG access control.

Workspace retrieval is scoped to a ``workspace_id`` (cross-workspace isolation,
enforced at SQL). This module adds the *intra*-workspace dimension: not every
member of a workspace may read every indexed chunk. A donation-rollup or
pipeline chunk carries financial / donor-adjacent facts the gated REST API only
exposes to owners and admins; without a tier gate the agent's broad retrieval
becomes a permission side-channel that hands those facts to any member.

The model is deliberately two-tier and pure (no Django, no I/O):

* ``GENERAL``    — any active member may read (identity, mission, team, …).
* ``RESTRICTED`` — owner / admin only (financial rollups, pipeline entities).

Retrieval maps the *viewer's* role to the set of tiers they may read; indexing
stamps each chunk with the tier its source section warrants. A chunk with no
tier stamped is treated as ``RESTRICTED`` by the reader's filter default
(fail-closed) — legacy rows are backfilled by migration.

Roles are read, never persona (ADR 0002).
"""

from __future__ import annotations

GENERAL = "general"
RESTRICTED = "restricted"

#: Roles that may read RESTRICTED chunks. Owner is resolved from workspace
#: ownership upstream; staff/superusers resolve to ``owner`` there too.
RESTRICTED_ROLES = frozenset({"owner", "admin"})

#: The autonomous AI service principal (the workspace's AI teammate user). It is
#: a trusted *internal reader* — the scheduled detector needs restricted facts
#: (financial rollups, pipeline) to surface findings — but it is capped for
#: writes/actions at the permission gate (see ``requires_role``), so it reads
#: everything and executes no privileged tool (SEE-201).
AI_SERVICE = "ai_service"

#: Snapshot section keys whose body carries owner/admin-only facts. Everything
#: else in the workspace snapshot is GENERAL. Kept next to the tier constants so
#: the indexer and any future auditor read one source of truth.
#: - ``recent_activity`` — 30-day donation counts + money totals.
#: - ``top_entities``    — current pipeline: donor/recipient names + amounts.
RESTRICTED_SECTION_KEYS = frozenset({"recent_activity", "top_entities"})


def allowed_sensitivities_for_role(role: str | None) -> tuple[str, ...]:
    """Return the tiers a viewer with *role* may read.

    ``None`` / unknown roles get GENERAL only — least privilege for callers
    that could not resolve an effective role.
    """
    normalised = (role or "").strip().lower()
    if normalised in RESTRICTED_ROLES or normalised == AI_SERVICE:
        return (GENERAL, RESTRICTED)
    return (GENERAL,)


def sensitivity_for_section(section_key: str) -> str:
    """Return the tier a workspace-snapshot section warrants."""
    if section_key in RESTRICTED_SECTION_KEYS:
        return RESTRICTED
    return GENERAL
