"""Domain policy for workspace role resolution and section visibility.

Pure business rules — no Django, no ORM, no infrastructure. Given facts
about a user's relationship to a workspace, returns their UX-tier role
(owner / admin / contributor / sponsor / volunteer / auditor / personal)
and which dashboard sections they should see.

Source of truth (per ADR 0002)
------------------------------
- ``WorkspaceMembership.role`` — RBAC tier (owner / admin / member /
  viewer). Drives permission decisions.
- ``WorkspaceMembership.persona`` — experience tier (admin / contributor
  / volunteer / sponsor / auditor / board_member). Drives sidebar /
  dashboard / copy variant routing.

The visible_sections list returned here is a UX concern, so it's
derived primarily from persona, with admin-tier roles upgrading the
visibility regardless of persona drift (e.g. a legacy row where
role=admin but persona=contributor still gets the admin sidebar).

The previous version of this policy guessed the role from "did this
user CREATE a team in this workspace?" — a pre-ADR-0002 heuristic
that broke when admins were granted via WorkspaceMembership.role
without ever creating a team. Henry hit this on CyberSecurity Awareness
where Shamir owned the teams and Henry was made admin via persona
invite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


# ── Section keys (stable API contract) ──────────────────────────────────

SECTION_AI = "ai"
SECTION_FUNDRAISING = "fundraising"
SECTION_TEAMS = "teams"
SECTION_FINANCE = "finance"
SECTION_PROJECTS = "projects"
SECTION_SETTINGS = "settings"
SECTION_SPONSORSHIP = "sponsorship"
SECTION_CAMPAIGNS = "campaigns"
SECTION_DONATIONS = "donations"
SECTION_GRANTS = "grants"
SECTION_TRANSPARENCY = "transparency"
SECTION_WORKFLOWS = "workflows"

# ── UX-tier role keys ───────────────────────────────────────────────────

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_CONTRIBUTOR = "contributor"
ROLE_VOLUNTEER = "volunteer"
ROLE_SPONSOR = "sponsor"
ROLE_AUDITOR = "auditor"
ROLE_BOARD_MEMBER = "board_member"
ROLE_PERSONAL = "personal"
ROLE_ADVISER = "adviser"

# ── Section visibility per UX-tier role ─────────────────────────────────
#
# Owner / admin / board_member get full visibility — they're running
# (or governing) the org. Contributor / volunteer share the team-focused
# subset. Sponsor / auditor share the read-only / transparency subset.
# Personal is the private-workspace tier: org-revenue surfaces (fundraising,
# sponsorship, campaigns, donations) stay off, but teams/projects are
# included so the Notion-style dual model keeps a coherent shell on both
# sides — a personal workspace still has its "Family" team + its projects.

_FULL_ADMIN_SECTIONS = [
    SECTION_AI,
    SECTION_FUNDRAISING,
    SECTION_TEAMS,
    SECTION_WORKFLOWS,
    SECTION_FINANCE,
    SECTION_PROJECTS,
    SECTION_SETTINGS,
    SECTION_SPONSORSHIP,
    SECTION_CAMPAIGNS,
    SECTION_DONATIONS,
    SECTION_GRANTS,
]

_TEAM_FOCUSED_SECTIONS = [
    SECTION_PROJECTS,
    SECTION_TEAMS,
    SECTION_WORKFLOWS,
    SECTION_AI,
]

_READ_ONLY_SECTIONS = [
    SECTION_TRANSPARENCY,
    SECTION_SPONSORSHIP,
    SECTION_DONATIONS,
    SECTION_GRANTS,
]

_PERSONAL_SECTIONS = [
    SECTION_AI,
    SECTION_FINANCE,
    SECTION_PROJECTS,
    SECTION_SETTINGS,
    SECTION_TEAMS,
]

# Adviser is a guest on someone else's personal workspace — the "family
# member helping" / "accountant reviewing" tier. Read-mostly finance with
# AI + projects context, no settings (not their workspace to configure).
# Mirrors Xero's "Adviser" role and the shape of QBOA's invited
# Accountant user. See docs/plans/GO_TO_MARKET_PLAN.md and the
# sidebar-pattern research synthesis (2026-06-13).
_ADVISER_SECTIONS = [
    SECTION_AI,
    SECTION_FINANCE,
    SECTION_PROJECTS,
]

_SECTIONS_BY_ROLE = {
    ROLE_OWNER: _FULL_ADMIN_SECTIONS,
    ROLE_ADMIN: _FULL_ADMIN_SECTIONS,
    ROLE_BOARD_MEMBER: _FULL_ADMIN_SECTIONS,
    ROLE_CONTRIBUTOR: _TEAM_FOCUSED_SECTIONS,
    ROLE_VOLUNTEER: _TEAM_FOCUSED_SECTIONS,
    ROLE_SPONSOR: _READ_ONLY_SECTIONS,
    ROLE_AUDITOR: _READ_ONLY_SECTIONS,
    ROLE_ADVISER: _ADVISER_SECTIONS,
    ROLE_PERSONAL: _PERSONAL_SECTIONS,
}

# ── RBAC role values that grant admin-tier visibility regardless of
# persona ──────────────────────────────────────────────────────────────
#
# These are the values stored on ``WorkspaceMembership.role`` (an
# RBAC tier per ADR 0002). When the membership.role is OWNER or
# ADMIN, the user always gets the full admin sidebar — even if their
# persona is, say, ``contributor`` (a legacy combination from before
# the persona-coercion fix landed). The reverse isn't true:
# persona=admin without role=admin is also valid (e.g. board members)
# and is handled by the persona mapping below.

_ADMIN_RBAC_ROLES = frozenset({"owner", "admin"})


@dataclass(frozen=True)
class WorkspaceRole:
    """Value object — a user's resolved UX-tier role on a workspace
    plus the section keys they should see in the sidebar."""

    role: str
    visible_sections: List[str]


def resolve_workspace_role(
    *,
    is_owner: bool,
    is_personal_workspace: bool,
    membership_role: Optional[str] = None,
    membership_persona: Optional[str] = None,
) -> WorkspaceRole:
    """Determine a user's UX-tier role on a workspace.

    Priority:
      1. Personal workspace AND owner → personal (the "my own books" tier).
      2. Workspace owner → owner.
      3. Membership.role indicates admin tier (owner / admin) → admin.
      4. Membership.persona dictates the experience tier
         (admin / contributor / volunteer / sponsor / auditor /
         board_member / adviser).
      5. Fallback (no membership row) → sponsor (read-only follower).

    Parameters
    ----------
    is_owner:
        ``Workspace.workspace_owner_id == user.id``.
    is_personal_workspace:
        ``Workspace.workspace_type == 'personal' and is_owner``. Note
        this is intentionally coupled to ownership — a non-owner with a
        membership on a personal workspace (Adviser, family member) gets
        ROLE_ADVISER via the persona branch, NOT ROLE_PERSONAL.
    membership_role:
        ``WorkspaceMembership.role`` for the user on the workspace, or
        ``None`` if no active membership row exists.
    membership_persona:
        ``WorkspaceMembership.persona`` — same lookup. Drives the UX
        tier when role is below admin.
    """

    if is_personal_workspace:
        return WorkspaceRole(
            role=ROLE_PERSONAL,
            visible_sections=list(_SECTIONS_BY_ROLE[ROLE_PERSONAL]),
        )

    if is_owner:
        return WorkspaceRole(
            role=ROLE_OWNER,
            visible_sections=list(_SECTIONS_BY_ROLE[ROLE_OWNER]),
        )

    rbac_role = (membership_role or "").strip().lower()
    if rbac_role in _ADMIN_RBAC_ROLES:
        # ADR 0002: role is the canonical RBAC signal. Admin tier
        # always gets full visibility regardless of persona drift.
        ux_role = ROLE_ADMIN if rbac_role == "admin" else ROLE_OWNER
        return WorkspaceRole(
            role=ux_role,
            visible_sections=list(_SECTIONS_BY_ROLE[ux_role]),
        )

    persona = (membership_persona or "").strip().lower()
    if persona in _SECTIONS_BY_ROLE:
        return WorkspaceRole(
            role=persona,
            visible_sections=list(_SECTIONS_BY_ROLE[persona]),
        )

    # Fallback: user has no active membership row (e.g. a follower who
    # was never enrolled). Treat as sponsor — read-only transparency
    # view.
    return WorkspaceRole(
        role=ROLE_SPONSOR,
        visible_sections=list(_SECTIONS_BY_ROLE[ROLE_SPONSOR]),
    )
