"""Guardrail: the gated use case is the ONLY creator of a RemediationEntry.

This is the structural expression of ADR 0012 D1 ("there is no other write
path"). If someone later adds a controller create endpoint, an admin add form, or
a second use case that constructs/persists a ``RemediationEntry`` bypassing the
gate, this test fails — the whole anti-poisoning posture rests on the gate being
the sole writer, so we enforce it with a fitness function, not just a comment.

Two things are asserted by scanning the ``remediation`` source:
1. ``RemediationEntry(`` (domain entity construction) appears only in the gated
   use case + the db mapper (ORM→domain read) + the entity's own module.
2. ``store.save(`` / repository ``.save(`` writes are reachable only from the
   gated use case (via the service) — no api/controller create path exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REMEDIATION_ROOT = Path(__file__).resolve().parents[2]  # components/remediation

# Files permitted to CONSTRUCT the RemediationEntry domain entity.
_ENTITY_CONSTRUCTION_ALLOWED = {
    "application/use_cases/record_remediation_entry_use_case.py",  # the gate — sole creator
    "mappers/db/remediation_entry_mapper.py",  # ORM row → entity (read path)
    "domain/entities/remediation_entry_entity.py",  # the .revoked() copy + defn
}

# Files permitted to call the store's write (`save`).
_STORE_WRITE_ALLOWED = {
    "application/use_cases/record_remediation_entry_use_case.py",  # gate writes admitted entry
    "infrastructure/repositories/remediation_entry_repository.py",  # the impl itself
    "tests",  # tests may exercise revocation save directly
}


def _rel(path: Path) -> str:
    return str(path.relative_to(_REMEDIATION_ROOT))


def _entity_construction_sites() -> list[str]:
    sites: list[str] = []
    for py in _REMEDIATION_ROOT.rglob("*.py"):
        rel = _rel(py)
        if rel.startswith("tests"):
            continue
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RemediationEntry":
                sites.append(rel)
                break
    return sites


def test_only_the_gate_constructs_the_entity():
    sites = set(_entity_construction_sites())
    unexpected = sites - _ENTITY_CONSTRUCTION_ALLOWED
    assert not unexpected, (
        f"RemediationEntry constructed outside the gate/mapper/entity: {sorted(unexpected)}. "
        "Corpus membership must be earned via RecordRemediationEntryUseCase (ADR 0012 D1)."
    )


def test_no_api_controller_create_path_exists():
    # A remediation controller may exist for READS, but must not offer any create
    # endpoint that bypasses the gate. Assert there is no controller writing entries.
    api_dir = _REMEDIATION_ROOT / "api"
    for py in api_dir.rglob("*.py"):
        text = py.read_text()
        assert "RemediationEntry(" not in text, f"{_rel(py)} constructs an entry — controllers must not."
        assert ".save(" not in text, f"{_rel(py)} writes to a store — no create endpoint may bypass the gate."


def test_store_writes_only_from_gate_and_impl():
    offenders: list[str] = []
    for py in _REMEDIATION_ROOT.rglob("*.py"):
        rel = _rel(py)
        if any(rel.startswith(allowed.rstrip("/")) for allowed in _STORE_WRITE_ALLOWED):
            continue
        text = py.read_text()
        if ".save(" in text:
            offenders.append(rel)
    assert not offenders, f"store .save() reached from outside the gate: {offenders}"
