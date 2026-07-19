"""Architecture tests are pure AST scanners — no DB, no test fixtures.

These tests walk source files under ``components/`` and ``infrastructure/``
to enforce import-rule guardrails (port placement, framework-free domain,
cross-context boundaries, etc.). They MUST NOT trigger pytest-django's
session-level ``django_db_setup`` fixture — that fixture creates the test
SQLite database under ``.pytest-dbs/`` (or worse, a ``test_*`` database in
local Postgres when ``DJANGO_SETTINGS_MODULE`` resolves to ``api.settings.local``).

This conftest:

1. Replaces the global ``django_db_setup`` fixture with a no-op so no
   database is provisioned for the architecture session.
2. Replaces the root ``default_sectors`` and ``default_system_roles``
   session-autouse fixtures with no-ops. They seed reference rows via
   ``django_db_blocker.unblock()`` and would fail under our blocked /
   non-provisioned DB.
3. Adds an autouse ``_block_db_access`` fixture that wraps every test in
   ``django_db_blocker.block()`` — if an arch test secretly queries the
   ORM (it shouldn't), pytest-django raises ``DatabaseAccessNotAllowed``
   immediately and the smell is surfaced loudly.

Per ``.claude/skills/testing/SKILL.md`` §0 HARD RULE 2 — unit/architecture
layers never use the real Django ORM.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def django_db_setup():
    """No-op override of pytest-django's session DB setup for arch tests."""
    yield


@pytest.fixture(scope="session", autouse=True)
def default_sectors():
    """No-op override: arch tests don't query ``Sector``."""
    yield


@pytest.fixture(scope="session", autouse=True)
def default_system_roles():
    """No-op override: arch tests don't query ``WorkspaceRole``."""
    yield


@pytest.fixture(autouse=True)
def _block_db_access(django_db_blocker):
    """Block ORM access in every architecture test.

    If an arch test accidentally queries the database, pytest-django raises
    ``DatabaseAccessNotAllowed`` so the violation surfaces immediately rather
    than silently passing on whatever data happens to be available.
    """
    with django_db_blocker.block():
        yield
