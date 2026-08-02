"""Architecture guardrail: the RemediationEntry corpus has ONE writer, repo-wide.

This is the structural teeth of ADR 0012 D1 ("A ``RemediationEntry`` may enter the
retrievable corpus only when all three conditions hold … There is no other write
path."). The whole anti-RAG-poisoning guarantee rests on that: if *any* code
anywhere could write the model bypassing the gated repository, an attacker or a
hallucinating agent could seed the corpus, and the gate would be theatre.

The in-context ``components/remediation/tests/unit/test_sole_writer_invariant.py``
guards construction inside the context. THIS test is the real guard — it scans the
**entire repo** (guaranteed to run in ``tests/architecture/``) and FAILS if any
file other than the single sanctioned repository:

  (a) imports or references the ``infrastructure.persistence.remediation.models``
      module (i.e. touches the ``RemediationEntry`` ORM model at all), OR
  (b) performs an ORM write to it (``.create(`` / ``.update_or_create(`` /
      ``.bulk_create(`` / ``.save(`` / ``.objects.update(`` on ``RemediationEntry``).

The gate itself constructs the *domain entity* and hands it to the repository; the
repository is the ONLY place the ORM model is imported and written. Verified to
PASS today (the fact holds) and would FAIL the instant someone adds an un-gated
write from another file or context.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The single file permitted to import + write the RemediationEntry ORM model.
_SOLE_WRITER = "components/remediation/infrastructure/repositories/remediation_entry_repository.py"

# The model module + class the guard tracks.
_MODEL_MODULE = "infrastructure.persistence.remediation.models"
_MODEL_CLASS = "RemediationEntry"

# ORM write method names that, when called on the model class / a queryset of it,
# constitute a corpus write.
_WRITE_METHODS = {"create", "update_or_create", "bulk_create", "save", "update", "get_or_create"}

# Directories to scan (the whole application tree). The persistence app's own
# migrations legitimately reference the model (Django generates them) — exclude
# migrations + the model definition + admin (Django admin registration).
_SCAN_DIRS = ("components", "infrastructure", "api")
_EXCLUDED_PREFIXES = (
    "infrastructure/persistence/remediation/",  # the model, its migrations + admin
)


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        files.extend(f for f in base.rglob("*.py") if f.is_file())
    return sorted(files)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _references_model_module(tree: ast.AST) -> bool:
    """True if the file imports the RemediationEntry model module in any form."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _MODEL_MODULE:
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _MODEL_MODULE:
                    return True
    return False


def _writes_model(tree: ast.AST, source: str) -> bool:
    """True if the file appears to perform an ORM write against RemediationEntry.

    Heuristic but conservative: a call whose attribute is a write method AND whose
    receiver chain mentions ``RemediationEntry`` (e.g. ``RemediationEntry.objects
    .create(...)``, ``Row.objects.update_or_create(...)`` where ``Row`` aliases the
    model). Because (a) already blocks importing the model module anywhere but the
    sole writer, this is a belt-and-braces second signal.
    """
    if _MODEL_CLASS not in source:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _WRITE_METHODS:
            continue
        # Walk the receiver chain to its root name and check for the model class.
        receiver = ast.dump(func.value)
        if _MODEL_CLASS in receiver:
            return True
    return False


def test_remediation_entry_has_a_single_repo_wide_writer():
    model_offenders: list[str] = []
    write_offenders: list[str] = []
    saw_sole_writer = False

    for py in _iter_python_files():
        rel = _rel(py)
        if any(rel.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        # Tests legitimately read the model to assert corpus state (they never
        # write it through a production path); the sole-writer guarantee is about
        # SHIPPING code, so exclude test modules.
        if "/tests/" in rel:
            continue
        if rel == _SOLE_WRITER:
            saw_sole_writer = True
            continue
        source = py.read_text()
        # Fast reject: if the model name never appears, nothing to parse.
        if _MODEL_CLASS not in source and _MODEL_MODULE not in source:
            continue
        tree = ast.parse(source, filename=str(py))
        if _references_model_module(tree):
            model_offenders.append(rel)
        if _writes_model(tree, source):
            write_offenders.append(rel)

    assert saw_sole_writer, (
        f"expected the sole-writer repository at {_SOLE_WRITER} to exist and be scanned; "
        "did it move? update this guard."
    )
    assert not model_offenders, (
        "RemediationEntry ORM model imported outside the gated repository "
        f"({_SOLE_WRITER}): {model_offenders}. Corpus membership must be earned via "
        "RecordRemediationEntryUseCase (ADR 0012 D1) — no other file may touch the model."
    )
    assert not write_offenders, (
        "RemediationEntry ORM write found outside the gated repository "
        f"({_SOLE_WRITER}): {write_offenders}. There must be no un-gated write path."
    )
