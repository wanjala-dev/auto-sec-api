"""The ``--tenant`` / ``--all-tenants`` argv split, on its own.

Pure argv handling — no Django, no database — because it runs BEFORE
``django.setup()`` and has to be correct there. The property that matters most
is the first test: with no flag, argv comes out byte-for-byte and the selection
is ``None``, which is what keeps ~99 existing commands behaving exactly as they
did.
"""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.tenancy.management import (
    TenantSelectionError,
    extract_tenant_selection,
)

pytestmark = pytest.mark.unit


class TestNoFlagIsTheUntouchedPath:
    def test_argv_passes_through_unchanged_and_selects_nothing(self):
        argv = ["manage.py", "reindex_workspaces", "--all", "--sync", "--force"]

        remaining, selection = extract_tenant_selection(argv)

        assert remaining == argv
        assert selection is None

    def test_an_empty_argv_is_not_a_selection(self):
        assert extract_tenant_selection([]) == ([], None)


class TestTheFlagsAreConsumedHere:
    def test_tenant_flag_is_stripped_so_the_command_never_sees_it(self):
        remaining, selection = extract_tenant_selection(
            ["manage.py", "reindex_workspaces", "--tenant", "faura", "--all", "--sync"]
        )

        assert remaining == ["manage.py", "reindex_workspaces", "--all", "--sync"]
        assert selection.subdomain == "faura"
        assert selection.all_tenants is False

    def test_equals_form_is_accepted(self):
        remaining, selection = extract_tenant_selection(["manage.py", "migrate", "--tenant=Acme"])

        assert remaining == ["manage.py", "migrate"]
        assert selection.subdomain == "acme"  # hostnames are case-insensitive

    def test_all_tenants_flag_is_stripped(self):
        remaining, selection = extract_tenant_selection(["manage.py", "reindex_workspaces", "--all-tenants", "--all"])

        assert remaining == ["manage.py", "reindex_workspaces", "--all"]
        assert selection.all_tenants is True
        assert selection.subdomain is None

    def test_all_is_not_confused_with_all_tenants(self):
        """``--all`` is a real flag on reindex_workspaces; it must survive."""
        remaining, selection = extract_tenant_selection(["manage.py", "reindex_workspaces", "--all"])

        assert remaining == ["manage.py", "reindex_workspaces", "--all"]
        assert selection is None


class TestAmbiguousInputIsRefused:
    """Every one of these could be "helpfully" defaulted. None of them is."""

    def test_tenant_without_a_value_raises(self):
        with pytest.raises(TenantSelectionError, match="needs a tenant subdomain"):
            extract_tenant_selection(["manage.py", "migrate", "--tenant"])

    def test_tenant_swallowing_the_next_flag_raises(self):
        with pytest.raises(TenantSelectionError, match="needs a tenant subdomain"):
            extract_tenant_selection(["manage.py", "migrate", "--tenant", "--sync"])

    def test_tenant_twice_raises_rather_than_picking_one(self):
        with pytest.raises(TenantSelectionError, match="more than once"):
            extract_tenant_selection(["manage.py", "migrate", "--tenant", "a", "--tenant", "b"])

    def test_both_flags_together_raise(self):
        with pytest.raises(TenantSelectionError, match="mutually exclusive"):
            extract_tenant_selection(["manage.py", "migrate", "--tenant", "faura", "--all-tenants"])
