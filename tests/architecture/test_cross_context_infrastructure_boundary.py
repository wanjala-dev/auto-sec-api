"""Architecture guardrail: application layers must not import another context's infrastructure.

A component's application layer (use cases, queries, providers) may depend on
another context through its **application** layer (providers, ports, DTOs) but
must **never** import directly from another context's infrastructure.

Allowed cross-context dependency paths::

    sponsorship.application → payments.application.providers  ✓
    sponsorship.application → payments.ports                  ✓
    sponsorship.application → payments.infrastructure         ✗ VIOLATION

Infrastructure-to-infrastructure cross-context imports are tracked but
not blocked (they are addressed separately in infrastructure consolidation).

This test enforces the rule:
  "Application layers may reach across contexts only through the other
   context's public API (application layer + ports)."
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# ── Transitional allowlist ─────────────────────────────────────────────
# (source_context, target_context) pairs where app→infra is temporarily OK.
# Each entry MUST have a tracking comment.
_TRANSITIONAL_ALLOWLIST: set[tuple[str, str]] = {
    # agents → knowledge: provider needs extraction to knowledge's application layer
    ("agents", "knowledge"),
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


def test_application_layers_do_not_import_other_contexts_infrastructure():
    """Application-layer code must not import another context's infrastructure."""
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

            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) < 3:
                    continue

                imported_ctx = parts[1]
                layer = parts[2]

                if imported_ctx == ctx or imported_ctx == "shared_kernel":
                    continue

                if layer == "infrastructure":
                    if (ctx, imported_ctx) in _TRANSITIONAL_ALLOWLIST:
                        continue
                    violations.append(
                        f"{src.relative_to(ROOT)} in '{ctx}' application "
                        f"imports '{imported_ctx}' infrastructure: {mod}. "
                        "Use the target context's application-layer "
                        "provider or port instead."
                    )

    assert not violations, (
        "Application layers must not import another context's infrastructure. "
        "Use the target context's application-layer providers or ports:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
