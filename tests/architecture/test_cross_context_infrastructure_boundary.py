"""Architecture guardrail: no context may import another context's infrastructure.

A component reaches another context only through its **application** layer
(providers, ports, DTOs) or the shared kernel — never by importing that context's
infrastructure directly.

Allowed cross-context dependency paths::

    sponsorship.application → payments.application.providers  ✓
    sponsorship.application → payments.ports                  ✓
    anything            → payments.infrastructure             ✗ VIOLATION

Two tests enforce this:

- ``test_application_layers_...`` — the application layer (use cases, queries,
  providers) may not import another context's infrastructure. A small
  ``_TRANSITIONAL_ALLOWLIST`` covers a few remaining app→infra imports pending
  port extraction.
- ``test_non_application_layers_...`` — **every other layer** (infrastructure,
  cli, mappers, api, workers, domain) may not import another context's
  infrastructure either, with **ZERO allowlist**. This closes the historical
  "infra→infra is tracked but not blocked" gap (ADR 0004 infra-boundary series,
  completed 2026-07): 71 such imports across 31 context-pairs were routed through
  the owning context's application-layer providers/ports. Do not re-introduce any.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# ── Transitional allowlist (APPLICATION layer only) ────────────────────
# (source_context, target_context) pairs where app→infra is temporarily OK.
# Each entry MUST have a tracking comment. The non-application test below has
# NO allowlist — infra/cli/mappers/api → other-context infrastructure is a hard
# failure.
_TRANSITIONAL_ALLOWLIST: set[tuple[str, str]] = {
    # campaigns → sponsorship: ledger_service needs a port/facade
    ("campaigns", "sponsorship"),
    # workspace → team: membership repo + ai teammate sync need port extraction
    ("workspace", "team"),
}


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


def _cross_context_infra_import(ctx: str, mod: str) -> str | None:
    """Return the imported foreign context if *mod* is another context's
    infrastructure, else ``None``. The shared kernel is always importable."""
    if not mod.startswith("components."):
        return None
    parts = mod.split(".")
    if len(parts) < 3:
        return None
    imported_ctx, layer = parts[1], parts[2]
    if imported_ctx == ctx or imported_ctx == "shared_kernel":
        return None
    return imported_ctx if layer == "infrastructure" else None


def _iter_contexts():
    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if ctx_dir.is_dir() and (ctx_dir / "__init__.py").exists():
            yield ctx_dir


def test_application_layers_do_not_import_other_contexts_infrastructure():
    """Application-layer code must not import another context's infrastructure."""
    violations: list[str] = []

    for ctx_dir in _iter_contexts():
        ctx = ctx_dir.name
        app_dir = ctx_dir / "application"
        if not app_dir.exists():
            continue

        for src in _iter_python_files(app_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                imported_ctx = _cross_context_infra_import(ctx, mod)
                if imported_ctx is None:
                    continue
                if (ctx, imported_ctx) in _TRANSITIONAL_ALLOWLIST:
                    continue
                violations.append(
                    f"{src.relative_to(ROOT)} in '{ctx}' application "
                    f"imports '{imported_ctx}' infrastructure: {mod}. "
                    "Use the target context's application-layer provider or port instead."
                )

    assert not violations, (
        "Application layers must not import another context's infrastructure. "
        "Use the target context's application-layer providers or ports:\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_non_application_layers_do_not_import_other_contexts_infrastructure():
    """Infrastructure / cli / mappers / api / workers / domain must not import
    another context's infrastructure — ZERO allowlist.

    Reach another context only through its application-layer providers/ports.
    This is the closed form of the historical "infra→infra tracked but not
    blocked" gap; keep it at zero.
    """
    violations: list[str] = []

    for ctx_dir in _iter_contexts():
        ctx = ctx_dir.name
        for src in _iter_python_files(ctx_dir):
            if src.name == "__init__.py":
                continue
            rel_top = src.relative_to(ctx_dir).parts[0]
            # application: enforced by the test above (with its transitional
            # allowlist). tests: fixtures may reach internals.
            if rel_top in ("application", "tests"):
                continue
            for mod in _imported_modules(src):
                imported_ctx = _cross_context_infra_import(ctx, mod)
                if imported_ctx is None:
                    continue
                violations.append(
                    f"{src.relative_to(ROOT)} in '{ctx}' imports '{imported_ctx}' "
                    f"infrastructure: {mod}. Reach the target context through its "
                    "application-layer provider/port (no allowlist)."
                )

    assert not violations, (
        "Cross-context infrastructure imports are forbidden outside the application "
        "layer (no allowlist). Route through the owning context's application-layer "
        "providers/ports:\n" + "\n".join(f"  - {v}" for v in violations)
    )
