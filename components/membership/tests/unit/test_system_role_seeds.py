"""Anti-drift tests for the system role seeds.

``SYSTEM_ROLE_SEEDS`` defines every system ``WorkspaceRole`` (owner / admin /
member / viewer) and the permission keys each carries. Those keys MUST stay
valid according to ``VALID_PERMISSION_KEYS``: if someone adds a new system role
— or a new permission to an existing one — and forgets to register the key in
the backend allow-list, the seed writes values the permission endpoints later
reject, and the role silently under-grants.

These are the invariants that make RBAC trustworthy on a security product, so
they are worth keeping sharp.

FORK-DRIFT REPAIR (2026-08-08)
------------------------------
These tests had been failing on every run with
``ModuleNotFoundError: infrastructure.persistence.workspaces.migrations.
0016_seed_system_roles`` — they imported the seeds from a data migration that
no longer exists (the fork reset migration history to fresh ``0001``s; see
CLAUDE.md "How to self-correct when the fork bites"). The seeds moved to the
``seed_workspace_roles`` management command, which is now the single canonical
source — the same one ``conftest.py`` seeds test roles from.

The expected role set was also nonprofit-era (campaign_manager,
donation_steward, finance, auditor). autosec's roles are owner / admin
(\"Root\") / member (\"Analyst\") / viewer, and ``auditor`` is a PERSONA here,
not a role (ADR 0002) — so the read-only invariant now targets ``viewer``, the
role that actually carries it.
"""

from __future__ import annotations

# The ONE canonical source of the system role seeds. Importing it directly
# (rather than re-deriving the path) means a future move breaks loudly here
# instead of silently skipping these invariants.
from components.workspace.cli.management.commands.seed_workspace_roles import (
    SYSTEM_ROLE_SEEDS,
)

# The roles autosec actually ships. Changing this set is a deliberate RBAC
# decision — update it consciously, never to make a red test green.
EXPECTED_SLUGS = {"owner", "admin", "member", "viewer"}

# Roles that must never carry a mutating capability.
READ_ONLY_SLUGS = {"viewer"}


def _seeds_by_slug() -> dict[str, set[str]]:
    return {slug: set(permissions) for slug, _name, _description, permissions in SYSTEM_ROLE_SEEDS}


def test_every_seeded_permission_is_in_valid_registry() -> None:
    from components.membership.api.groups_controller import VALID_PERMISSION_KEYS

    for slug, permissions in _seeds_by_slug().items():
        unknown = permissions - VALID_PERMISSION_KEYS
        assert not unknown, (
            f"System role {slug!r} references permission keys not in VALID_PERMISSION_KEYS: {sorted(unknown)}"
        )


def test_seeds_cover_expected_slugs() -> None:
    slugs = set(_seeds_by_slug())
    assert slugs == EXPECTED_SLUGS, (
        "System role seed set changed; update this test deliberately if "
        f"intentional. missing={sorted(EXPECTED_SLUGS - slugs)}, "
        f"extra={sorted(slugs - EXPECTED_SLUGS)}"
    )


def test_owner_and_admin_cover_every_valid_permission() -> None:
    """Owner and Admin are full-access — surface drift the moment a new
    permission enters the registry without being granted to them."""
    from components.membership.api.groups_controller import VALID_PERMISSION_KEYS

    seeds = _seeds_by_slug()
    for slug in ("owner", "admin"):
        missing = VALID_PERMISSION_KEYS - seeds[slug]
        assert not missing, f"{slug.title()} is missing permissions: {sorted(missing)}"


def test_read_only_roles_have_no_mutating_permissions() -> None:
    """A read-only role must never carry manage_* or run_* — the invariant
    that keeps 'viewer' genuinely read-only (and the one the RBAC capability
    gates are trusted to enforce elsewhere)."""
    seeds = _seeds_by_slug()
    for slug in READ_ONLY_SLUGS:
        mutating = {p for p in seeds[slug] if p.startswith(("manage_", "run_"))}
        assert not mutating, f"{slug!r} should be read-only but carries mutating permissions: {sorted(mutating)}"


def test_every_role_is_a_subset_of_owner() -> None:
    """No role may grant something the owner does not have — owner is the
    ceiling. Catches a permission added to a narrower role but never
    registered in the full-access set."""
    seeds = _seeds_by_slug()
    owner = seeds["owner"]
    for slug, permissions in seeds.items():
        beyond = permissions - owner
        assert not beyond, f"{slug!r} grants permissions the owner lacks: {sorted(beyond)}"
