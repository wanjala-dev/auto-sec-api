"""Unified application-layer purity guardrail.

The application layer (``components/<ctx>/application/``) must be
framework-free and must not import legacy ``apps.*`` modules.  It may
only depend on:

  * Python stdlib
  * Its own bounded context's domain, ports, and other application code
  * ``components.shared_kernel``
  * ``components.<ctx>.infrastructure.*`` **only** from provider files
    (composition roots) that wire adapters to ports

This single test replaces the per-context ``test_<ctx>_application_import_rules``
files by scanning **every** context automatically.  A new context gets the
guardrail for free the moment ``components/<ctx>/application/`` exists.

Banned prefix rationale:

  * ``apps`` — legacy Django app layer; must be behind ports/adapters
  * ``django`` — framework dependency belongs in infrastructure
  * ``rest_framework`` — presentation concern
  * ``celery`` — infrastructure concern
  * ``stripe`` / ``braintree`` — payment provider SDKs
  * ``requests`` — HTTP client, infrastructure
  * ``redis`` — cache/messaging, infrastructure
  * ``elasticsearch`` / ``elasticsearch_dsl`` — search infrastructure
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# ── Canonical banned prefixes ──────────────────────────────────────────
# Every context's application layer is checked against this set.
BANNED_PREFIXES = {
    "apps",
    "django",
    "rest_framework",
    "celery",
    "stripe",
    "braintree",
    "requests",
    "redis",
    "elasticsearch",
    "elasticsearch_dsl",
}

# ── Transitional allowlist ─────────────────────────────────────────────
# (context, file_stem) pairs that are temporarily exempt.
# Each entry MUST have a tracking comment explaining what blocks removal.
_TRANSITIONAL_ALLOWLIST: set[tuple[str, str]] = set()


def _iter_python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(f for f in path.rglob("*.py") if f.is_file())


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


def test_all_application_layers_are_framework_and_legacy_import_free():
    """Every context's application layer must be free of banned imports.

    Scans ``components/*/application/`` for imports from framework
    packages or legacy ``apps.*`` modules.  Violations indicate that
    business logic depends on infrastructure — extract behind a port.
    """
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name

        app_dir = ctx_dir / "application"
        if not app_dir.exists():
            continue

        for src in _iter_python_files(app_dir):
            if src.name == "__init__.py":
                continue

            if (ctx, src.stem) in _TRANSITIONAL_ALLOWLIST:
                continue

            for mod in _imported_modules(src):
                prefix = mod.split(".", 1)[0]
                if prefix in BANNED_PREFIXES:
                    violations.append(
                        f"{src.relative_to(ROOT)} in '{ctx}' application "
                        f"imports banned module: {mod}"
                    )

    assert not violations, (
        "Application layers must not import framework or legacy modules "
        "(extract behind a port/adapter):\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_all_port_layers_are_framework_free():
    """Every context's ports layer must be framework-free.

    Ports define contracts using Python ABCs, Protocols, and dataclasses.
    They must not import Django, DRF, or any infrastructure library.
    """
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name

        ports_dir = ctx_dir / "ports"
        if not ports_dir.exists():
            continue

        for src in _iter_python_files(ports_dir):
            if src.name == "__init__.py":
                continue

            for mod in _imported_modules(src):
                prefix = mod.split(".", 1)[0]
                if prefix in BANNED_PREFIXES:
                    violations.append(
                        f"{src.relative_to(ROOT)} in '{ctx}' ports "
                        f"imports banned module: {mod}"
                    )

    assert not violations, (
        "Port layers must not import framework or legacy modules:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
