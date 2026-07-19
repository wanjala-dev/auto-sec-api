"""Anti-drift tests for the system role seed migration.

The ``0016_seed_system_roles`` data migration references permission keys
that MUST be valid according to
``components.workspace.api.groups_controller.VALID_PERMISSION_KEYS``.
If someone adds a new system role (or a new permission to an existing
role) and forgets to register the key in the backend allow-list, the
seed will write values that the permission-list endpoint will later
reject. This test catches that divergence.
"""

from __future__ import annotations

import importlib


def _load_seeds() -> list[tuple]:
    module = importlib.import_module(
        "infrastructure.persistence.workspaces.migrations.0016_seed_system_roles"
    )
    return module.SYSTEM_ROLE_SEEDS


def test_every_seeded_permission_is_in_valid_registry() -> None:
    from components.membership.api.groups_controller import VALID_PERMISSION_KEYS

    seeds = _load_seeds()
    for slug, _name, _description, permissions in seeds:
        unknown = set(permissions) - VALID_PERMISSION_KEYS
        assert not unknown, (
            f"System role {slug!r} references permission keys not in "
            f"VALID_PERMISSION_KEYS: {sorted(unknown)}"
        )


def test_seeds_cover_expected_slugs() -> None:
    seeds = _load_seeds()
    slugs = {slug for slug, *_ in seeds}
    expected = {
        "owner",
        "admin",
        "campaign_manager",
        "donation_steward",
        "finance",
        "auditor",
        "member",
        "viewer",
    }
    assert slugs == expected, (
        "System role seed set changed; update this test deliberately if "
        f"intentional. missing={expected - slugs}, extra={slugs - expected}"
    )


def test_owner_and_admin_cover_every_valid_permission() -> None:
    """Owner and Admin are meant to be full-access — surface drift if a
    new permission is added to the registry without being added to them."""
    from components.membership.api.groups_controller import VALID_PERMISSION_KEYS

    seeds = {slug: set(perms) for slug, _name, _desc, perms in _load_seeds()}
    assert seeds["owner"] == VALID_PERMISSION_KEYS, (
        f"Owner is missing permissions: {sorted(VALID_PERMISSION_KEYS - seeds['owner'])}"
    )
    assert seeds["admin"] == VALID_PERMISSION_KEYS, (
        f"Admin is missing permissions: {sorted(VALID_PERMISSION_KEYS - seeds['admin'])}"
    )


def test_auditor_is_read_only() -> None:
    """Auditor must never have a manage_* permission."""
    seeds = {slug: set(perms) for slug, _name, _desc, perms in _load_seeds()}
    manage_perms = {p for p in seeds["auditor"] if p.startswith("manage_")}
    assert not manage_perms, (
        f"Auditor should be read-only but has manage_* permissions: {sorted(manage_perms)}"
    )
