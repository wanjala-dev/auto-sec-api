"""Unit tests for ``resolve_workspace_role``.

Pin down the persona/role → visibility-tier mapping. The policy used
to guess the role from ``team.created_by`` (a pre-ADR-0002 heuristic),
which incorrectly resolved admins to sponsor-tier visibility when they
hadn't created any team. The new policy reads ``WorkspaceMembership.role``
+ ``.persona`` directly, so admin-tier RBAC roles always grant full
sidebar visibility regardless of persona drift.
"""

from __future__ import annotations

import pytest

from components.identity.domain.policies.workspace_role_policy import (
    ROLE_ADMIN,
    ROLE_ADVISER,
    ROLE_AUDITOR,
    ROLE_BOARD_MEMBER,
    ROLE_CONTRIBUTOR,
    ROLE_OWNER,
    ROLE_PERSONAL,
    ROLE_SPONSOR,
    ROLE_VOLUNTEER,
    SECTION_AI,
    SECTION_FINANCE,
    SECTION_FUNDRAISING,
    SECTION_PROJECTS,
    SECTION_SETTINGS,
    SECTION_SPONSORSHIP,
    SECTION_TEAMS,
    SECTION_TRANSPARENCY,
    SECTION_WORKFLOWS,
    resolve_workspace_role,
)


# ── Personal-workspace short-circuit ────────────────────────────────────

def test_personal_workspace_resolves_to_personal_regardless_of_role():
    role = resolve_workspace_role(
        is_owner=True,
        is_personal_workspace=True,
        membership_role="admin",
        membership_persona="admin",
    )
    assert role.role == ROLE_PERSONAL
    assert SECTION_FUNDRAISING not in role.visible_sections
    assert SECTION_PROJECTS in role.visible_sections
    # Notion-style dual model: a personal workspace still has its "Family"
    # team + projects, so the Teams section is part of the personal shell.
    assert SECTION_TEAMS in role.visible_sections


# ── Owner short-circuit ────────────────────────────────────────────────

def test_workspace_owner_always_resolves_to_owner_tier():
    role = resolve_workspace_role(
        is_owner=True,
        is_personal_workspace=False,
        membership_role=None,
        membership_persona=None,
    )
    assert role.role == ROLE_OWNER
    assert SECTION_SETTINGS in role.visible_sections
    assert SECTION_TEAMS in role.visible_sections
    assert SECTION_FINANCE in role.visible_sections


# ── RBAC role admin/owner upgrades regardless of persona drift ──────────

@pytest.mark.parametrize(
    "rbac_role,persona,expected_role",
    [
        ("admin", "contributor", ROLE_ADMIN),
        ("admin", "sponsor", ROLE_ADMIN),
        ("admin", "admin", ROLE_ADMIN),
        ("owner", "contributor", ROLE_OWNER),
        ("owner", "admin", ROLE_OWNER),
    ],
)
def test_admin_or_owner_rbac_role_grants_full_visibility(
    rbac_role, persona, expected_role
):
    """An admin/owner RBAC role gets full sidebar visibility even if the
    persona is contributor/sponsor (legacy combinations from before the
    persona-coercion fix)."""
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role=rbac_role,
        membership_persona=persona,
    )
    assert role.role == expected_role
    assert SECTION_SETTINGS in role.visible_sections
    assert SECTION_TEAMS in role.visible_sections
    assert SECTION_FINANCE in role.visible_sections
    assert SECTION_FUNDRAISING in role.visible_sections


# ── Persona drives the tier when role is below admin ───────────────────

@pytest.mark.parametrize(
    "persona,expected_role,expected_section,unexpected_section",
    [
        # Contributor / volunteer → team-focused subset (no fundraising,
        # no settings).
        ("contributor", ROLE_CONTRIBUTOR, SECTION_PROJECTS, SECTION_FUNDRAISING),
        ("volunteer", ROLE_VOLUNTEER, SECTION_TEAMS, SECTION_SETTINGS),
        # Sponsor / auditor → read-only / transparency subset.
        ("sponsor", ROLE_SPONSOR, SECTION_TRANSPARENCY, SECTION_TEAMS),
        ("auditor", ROLE_AUDITOR, SECTION_SPONSORSHIP, SECTION_FINANCE),
        # Board member → full admin visibility (governance).
        ("board_member", ROLE_BOARD_MEMBER, SECTION_FUNDRAISING, None),
    ],
)
def test_persona_drives_visibility_tier_for_non_admin_roles(
    persona, expected_role, expected_section, unexpected_section
):
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="member" if expected_role != ROLE_BOARD_MEMBER else "viewer",
        membership_persona=persona,
    )
    assert role.role == expected_role
    assert expected_section in role.visible_sections
    if unexpected_section is not None:
        assert unexpected_section not in role.visible_sections


def test_workflows_section_visible_to_admin_and_contributor():
    """Workflows is part of the team-focused workflow for both admin
    (full sidebar) and contributor/volunteer (team-focused subset)."""
    admin = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="admin",
        membership_persona="admin",
    )
    contrib = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="member",
        membership_persona="contributor",
    )
    assert SECTION_WORKFLOWS in admin.visible_sections
    assert SECTION_WORKFLOWS in contrib.visible_sections


# ── Fallback when no membership row at all ─────────────────────────────

def test_no_membership_falls_back_to_sponsor():
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role=None,
        membership_persona=None,
    )
    assert role.role == ROLE_SPONSOR
    assert SECTION_TRANSPARENCY in role.visible_sections
    # And the sponsor never sees admin / team surfaces.
    assert SECTION_SETTINGS not in role.visible_sections
    assert SECTION_TEAMS not in role.visible_sections


def test_unknown_persona_falls_back_to_sponsor_tier():
    """An unrecognised persona string (data corruption / migration bug)
    must NOT silently grant admin visibility."""
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="member",
        membership_persona="alien",
    )
    assert role.role == ROLE_SPONSOR


# ── Adviser — guest on someone else's personal workspace ───────────────


def test_adviser_persona_resolves_to_read_mostly_finance_tier():
    """Adviser is the 'family member helping' / 'accountant reviewing'
    tier — non-owner with a membership on someone else's personal
    workspace. Read-mostly finance, no settings (not their workspace
    to configure)."""
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="viewer",
        membership_persona="adviser",
    )
    assert role.role == ROLE_ADVISER
    # Sees the financial picture they were invited to advise on.
    assert SECTION_FINANCE in role.visible_sections
    assert SECTION_AI in role.visible_sections
    assert SECTION_PROJECTS in role.visible_sections
    # Does NOT get settings, fundraising (org-revenue surface), or
    # transparency-only views — those don't apply on a personal
    # workspace.
    assert SECTION_SETTINGS not in role.visible_sections
    assert SECTION_FUNDRAISING not in role.visible_sections
    assert SECTION_TRANSPARENCY not in role.visible_sections


def test_adviser_does_not_get_personal_tier_even_on_personal_workspace():
    """A non-owner with persona=adviser on a personal workspace gets
    ROLE_ADVISER, NOT ROLE_PERSONAL — ROLE_PERSONAL is reserved for
    the workspace's actual owner. is_personal_workspace is False for
    non-owners by construction in the controller."""
    role = resolve_workspace_role(
        is_owner=False,
        is_personal_workspace=False,
        membership_role="viewer",
        membership_persona="adviser",
    )
    assert role.role == ROLE_ADVISER


# ── Visibility lists are isolated per call (defensive) ──────────────────

def test_visible_sections_lists_are_distinct_across_calls():
    a = resolve_workspace_role(
        is_owner=True,
        is_personal_workspace=False,
        membership_role=None,
        membership_persona=None,
    )
    b = resolve_workspace_role(
        is_owner=True,
        is_personal_workspace=False,
        membership_role=None,
        membership_persona=None,
    )
    a.visible_sections.append("__not_a_real_section__")
    assert "__not_a_real_section__" not in b.visible_sections
