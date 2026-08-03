"""Architecture guardrails for the contextual-risk scorer (ADR 0013 D3 / ADR 0004 C3-C4).

1. **The scorer is a pure domain service** — no framework, no I/O, no cross-context
   infrastructure. It reads intel + exposure through ports injected by the use case, never
   by importing another context (C3).
2. **FindingRisk correlates by value-identity, not a cross-context FK** — its only
   relations are to same-context ``Finding`` + the shared ``Workspace``; it must not hold a
   ForeignKey into cloud_graph (``CloudAsset``) or vuln_intel snapshots (C4). EPSS/KEV and
   exposure are joined by CVE id / AssetUrn through ports, never a hard FK.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCORER = ROOT / "components/findings/domain/services/contextual_risk_scorer.py"
_MODELS = ROOT / "infrastructure/persistence/findings/models.py"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_scorer_is_pure_no_framework_or_cross_context_infra():
    mods = _imported_modules(_SCORER)
    banned_prefixes = ("django", "celery", "rest_framework", "infrastructure.")
    offenders = sorted(m for m in mods if m.startswith(banned_prefixes))
    # It may import ONLY stdlib + its own shared_kernel value objects.
    cross_context = sorted(
        m
        for m in mods
        if m.startswith("components.")
        and not m.startswith("components.shared_kernel.")
        and not m.startswith("components.findings.")
    )
    assert not offenders, f"contextual_risk_scorer must be framework/infra-free: {offenders}"
    assert not cross_context, f"contextual_risk_scorer must not import another context: {cross_context}"


def test_finding_risk_has_no_cross_context_foreign_key():
    """FindingRisk must correlate by identity, not a FK into cloud_graph / vuln_intel (C4)."""
    source = _MODELS.read_text()
    tree = ast.parse(source, filename=str(_MODELS))

    # Find the FindingRisk class body and collect the model names referenced in relation
    # fields (ForeignKey/OneToOneField). Only Finding + Workspace are allowed.
    allowed_relation_targets = {"Finding", "Workspace"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "FindingRisk"):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in ("ForeignKey", "OneToOneField", "ManyToManyField"):
                continue
            target = call.args[0] if call.args else None
            name = None
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            elif isinstance(target, ast.Constant) and isinstance(target.value, str):
                name = target.value.split(".")[-1]
            if name and name not in allowed_relation_targets:
                offenders.append(name)

    assert not offenders, (
        "FindingRisk must not hold a cross-context ForeignKey (correlate by CVE/AssetUrn "
        f"via ports, ADR 0004 C4). Offending relation targets: {offenders}"
    )
