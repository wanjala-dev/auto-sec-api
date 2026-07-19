"""Unit tests MUST NOT use ``@pytest.mark.django_db`` — testing skill HARD RULE 2.

Per ``.claude/skills/testing/SKILL.md`` §0 HARD RULE 2:

> Unit tests enter through the use case, not through internal classes. A unit
> test talks only to the user-side / driving-port API … It knows nothing about
> the internal entities, the repositories, the ORM, the framework, or the HTTP
> transport. Driven ports are stubbed with in-memory fakes — never the real
> Django ORM repository, never ``@pytest.mark.django_db``.

This test walks every file under ``components/*/tests/unit/`` and fails if it
references ``@pytest.mark.django_db`` (decorator) or
``pytestmark = pytest.mark.django_db`` (module-level marker).

Tests that need a real database belong under ``components/<ctx>/tests/integration/``,
not ``tests/unit/``. If a unit test "needs" a DB, the use case under test is
either too tightly coupled to the ORM (refactor to talk to a port) or the test
is mislabelled (move it to ``integration/``).

A small allowlist of pre-existing violations is permitted to ship the guardrail
without blocking on a context-by-context cleanup; the list MUST shrink over time
and additions MUST NOT be made without explicit architectural review.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPONENTS_ROOT = REPO_ROOT / "components"

# Files known to use ``@pytest.mark.django_db`` today. These are pre-existing
# drift from HARD RULE 2 and should be migrated to integration/ (or refactored
# to use in-memory fakes) over time. New entries to this list require a
# tracked cleanup task and explicit reviewer approval — the list MUST NOT
# silently grow.
KNOWN_VIOLATIONS = frozenset(
    {
        # membership — permission service still reads ORM rows directly;
        # follow-up: extract WorkspaceMembershipReader port.
        "membership/tests/unit/test_membership_permission_service.py",
        # money — Stripe account currency adapter touches DB-backed model.
        "money/tests/unit/test_stripe_account_currency_adapter.py",
        # payments — ORM repository tests mislabelled as unit; should move to
        # integration/ in the next payments cleanup pass.
        "payments/tests/unit/test_connect_time_settlement_currency.py",
        "payments/tests/unit/test_orm_payment_event_claim_repository.py",
        "payments/tests/unit/test_orm_payment_event_recording_repository.py",
        "payments/tests/unit/test_orm_payment_flow_state_repository.py",
        "payments/tests/unit/test_orm_payment_order_repository.py",
        "payments/tests/unit/test_payment_event_state.py",
        "payments/tests/unit/test_payment_method_management_repository.py",
    }
)

# Patterns we treat as ``django_db`` markers — covers the decorator form,
# the module-level ``pytestmark = …`` form, and ``pytestmark = [pytest.mark.django_db, …]``
# list assignment. Comments / docstrings that mention the marker are excluded
# by checking the start of each line (after stripping leading whitespace).
_DJANGO_DB_PATTERN = re.compile(
    r"(?:^\s*@pytest\.mark\.django_db\b)|"
    r"(?:^\s*pytestmark\s*=\s*(?:\[[^\]]*)?pytest\.mark\.django_db\b)",
    re.MULTILINE,
)


def _relative_path(path: Path) -> str:
    """Return the components-relative slash path used in the allowlist."""
    return path.relative_to(COMPONENTS_ROOT).as_posix()


def _file_uses_django_db(path: Path) -> bool:
    """True if the file declares ``@pytest.mark.django_db`` outside a comment."""
    text = path.read_text(encoding="utf-8")
    return bool(_DJANGO_DB_PATTERN.search(text))


def test_no_new_unit_tests_use_django_db_marker():
    """Fail when a unit-test file outside the allowlist marks ``django_db``.

    HARD RULE 2 of the testing skill: unit tests use in-memory port fakes,
    never the real Django ORM. New unit tests that need ``django_db`` are
    almost always mislabelled integration tests — move them to
    ``components/<ctx>/tests/integration/`` instead of adding to the allowlist.
    """
    offenders: list[str] = []
    for unit_dir in COMPONENTS_ROOT.glob("*/tests/unit"):
        if not unit_dir.is_dir():
            continue
        for path in unit_dir.rglob("test_*.py"):
            if not path.is_file():
                continue
            rel = _relative_path(path)
            if rel in KNOWN_VIOLATIONS:
                continue
            if _file_uses_django_db(path):
                offenders.append(rel)

    assert not offenders, (
        "The following unit-test files use @pytest.mark.django_db. Per the "
        "testing skill SKILL.md §0 HARD RULE 2, unit tests must use in-memory "
        "port fakes (one per port, under components/<ctx>/tests/fakes/) — never "
        "the real Django ORM. Move these tests to "
        "components/<ctx>/tests/integration/ or refactor the use case to talk "
        "to a port:\n\n  - " + "\n  - ".join(sorted(offenders))
    )


def test_allowlist_only_contains_existing_files():
    """The KNOWN_VIOLATIONS list must not reference deleted/renamed files.

    Without this guard, the allowlist grows stale: a file is removed during a
    cleanup pass but its allowlist entry is forgotten, masking a future
    regression at the same path. Failing here forces the allowlist to track
    reality.
    """
    missing = sorted(
        rel for rel in KNOWN_VIOLATIONS
        if not (COMPONENTS_ROOT / rel).exists()
    )
    assert not missing, (
        "KNOWN_VIOLATIONS references files that no longer exist. Remove the "
        "stale allowlist entries:\n\n  - " + "\n  - ".join(missing)
    )


def test_allowlist_entries_actually_use_django_db():
    """Allowlist must not contain files that have already been cleaned up.

    If a previously-violating test was refactored off ``django_db`` but its
    allowlist entry was left behind, the allowlist becomes a misleading
    historical artifact. Failing here forces removal of cleaned-up entries
    so the list represents current technical debt, not past.
    """
    cleaned: list[str] = []
    for rel in KNOWN_VIOLATIONS:
        path = COMPONENTS_ROOT / rel
        if not path.exists():
            continue  # caught by the previous test
        if not _file_uses_django_db(path):
            cleaned.append(rel)

    assert not cleaned, (
        "KNOWN_VIOLATIONS lists files that no longer use "
        "@pytest.mark.django_db. Remove them from the allowlist to keep it "
        "honest:\n\n  - " + "\n  - ".join(sorted(cleaned))
    )
