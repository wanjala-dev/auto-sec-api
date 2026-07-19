"""Architecture guardrails enforcing hexagonal boundary rules.

These tests validate the rules defined in:
    .claude/rules/bounded-context-structure.md (single source of truth)
    .claude/rules/architecture-manifesto.md (Rules 9 and 10)

Tests:
    1. No infrastructure/providers/ directories exist (Rule 9)
    2. Controllers do not import vendor SDKs directly (Rule 10)
    3. All providers live in application/providers/ (Rule 9)
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# SDKs that must NEVER appear in controller imports.
# Adapters in infrastructure/ handle these — controllers go through ports.
BANNED_CONTROLLER_SDKS = {
    "stripe",
    "braintree",
    "langchain",
    "langchain_community",
    "langchain_openai",
    "langchain_anthropic",
    "elasticsearch",
    "elasticsearch_dsl",
    "openai",
    "anthropic",
}


def _iter_contexts():
    return sorted(
        d.name
        for d in COMPONENTS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )


def _imported_modules(source_file: Path) -> set[str]:
    try:
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


# ── Test 1: No infrastructure/providers/ directories ─────────────────


def test_no_providers_in_infrastructure():
    """Providers are composition roots — they belong in application/providers/,
    never in infrastructure/providers/.

    See: .claude/rules/bounded-context-structure.md — Rule 4
    See: .claude/rules/architecture-manifesto.md — Rule 9
    """
    violations = []
    for ctx in _iter_contexts():
        infra_providers = COMPONENTS_DIR / ctx / "infrastructure" / "providers"
        if infra_providers.is_dir():
            py_files = [
                f.name for f in infra_providers.iterdir()
                if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
            ]
            if py_files:
                violations.append(
                    f"components/{ctx}/infrastructure/providers/ contains "
                    f"provider files: {', '.join(py_files)}. "
                    f"Move to components/{ctx}/application/providers/"
                )
            elif infra_providers.exists():
                violations.append(
                    f"components/{ctx}/infrastructure/providers/ directory exists "
                    f"(even if empty). Remove it to avoid confusion."
                )

    assert not violations, (
        "Providers MUST live in application/providers/, NEVER in infrastructure/providers/.\n"
        "See .claude/rules/bounded-context-structure.md — Rule 4.\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ── Test 2: Controllers must not import vendor SDKs ──────────────────


def test_controllers_do_not_import_vendor_sdks():
    """Controllers must access infrastructure through ports, never import
    vendor SDKs directly.

    See: .claude/rules/bounded-context-structure.md — Rule 7
    See: .claude/rules/architecture-manifesto.md — Rule 10
    """
    violations = []

    for ctx in _iter_contexts():
        api_dir = COMPONENTS_DIR / ctx / "api"
        if not api_dir.is_dir():
            continue
        for src in sorted(api_dir.rglob("*.py")):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                top_level = mod.split(".")[0]
                if top_level in BANNED_CONTROLLER_SDKS:
                    violations.append(
                        f"{src.relative_to(ROOT)} imports '{mod}'. "
                        f"Use the port/adapter pattern instead of importing {top_level} directly."
                    )

    assert not violations, (
        "Controllers must NOT import vendor SDKs directly (Rule 10).\n"
        "Use ports and adapters — the adapter handles the SDK.\n"
        "See .claude/rules/architecture-manifesto.md — Rule 10.\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ── Test 3: All providers in correct location ────────────────────────


def test_all_providers_in_application_layer():
    """Provider directories must only exist under application/providers/.

    Files with 'provider' in the name may exist elsewhere (ports, use cases,
    resources) — this test checks for misplaced providers/ DIRECTORIES, not
    individual files.

    See: .claude/rules/bounded-context-structure.md — Rule 4
    """
    violations = []

    for ctx in _iter_contexts():
        ctx_dir = COMPONENTS_DIR / ctx
        # Find all directories named "providers" that are NOT in application/
        for providers_dir in sorted(ctx_dir.rglob("providers")):
            if not providers_dir.is_dir():
                continue
            rel = providers_dir.relative_to(ctx_dir)
            parts = rel.parts
            # application/providers/ is correct
            if len(parts) >= 2 and parts[0] == "application" and parts[-1] == "providers":
                continue
            # tests/ is fine
            if "tests" in parts:
                continue
            # Check if it has actual provider files (not just __init__.py)
            py_files = [
                f.name for f in providers_dir.iterdir()
                if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
            ]
            if py_files:
                violations.append(
                    f"components/{ctx}/{rel}/ contains provider files: "
                    f"{', '.join(py_files)}. Move to application/providers/"
                )
            elif providers_dir.exists():
                violations.append(
                    f"components/{ctx}/{rel}/ directory exists (even if empty). "
                    f"Remove it to avoid confusion."
                )

    assert not violations, (
        "Provider files must live in application/providers/.\n"
        "See .claude/rules/bounded-context-structure.md — Rule 4.\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
