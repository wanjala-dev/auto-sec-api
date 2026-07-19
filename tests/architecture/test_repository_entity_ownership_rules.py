"""Architecture guardrail: repositories must not return cross-component entities.

A repository in ``components/<ctx>/infrastructure/repositories/`` should only
import and return entities from its own bounded context's domain layer
(``components/<ctx>/domain/entities/``).

Importing another context's entities signals that the repository is violating
aggregate boundaries — it should instead return its own projections/DTOs
or delegate through an anti-corruption layer port.

This test enforces the Resilience-Model rule:
  "repositories may read across related tables, but they may only rehydrate
   and return entities owned by their own component or aggregate"
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"


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


def test_repositories_do_not_import_other_contexts_entities():
    """Repositories should only import entities from their own bounded context."""
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name
        if ctx == "shared_kernel":
            continue  # shared kernel is cross-context by design

        repo_dir = ctx_dir / "infrastructure" / "repositories"
        for src in _iter_python_files(repo_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) < 4:
                    continue
                imported_ctx = parts[1]
                layer = parts[2]
                sublayer = parts[3] if len(parts) > 3 else ""

                if (
                    imported_ctx != ctx
                    and imported_ctx != "shared_kernel"
                    and layer == "domain"
                    and sublayer == "entities"
                ):
                    violations.append(
                        f"{src.relative_to(ROOT)} in '{ctx}' imports "
                        f"entities from '{imported_ctx}': {mod}. "
                        "Repositories must only return entities owned "
                        "by their own bounded context."
                    )

    assert not violations, (
        "Repositories must not import or return entities from other "
        "bounded contexts:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_adapters_do_not_import_other_contexts_entities():
    """Infrastructure adapters should not import entities from other contexts."""
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name
        if ctx == "shared_kernel":
            continue

        adapter_dir = ctx_dir / "infrastructure" / "adapters"
        for src in _iter_python_files(adapter_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) < 4:
                    continue
                imported_ctx = parts[1]
                layer = parts[2]
                sublayer = parts[3] if len(parts) > 3 else ""

                if (
                    imported_ctx != ctx
                    and imported_ctx != "shared_kernel"
                    and layer == "domain"
                    and sublayer == "entities"
                ):
                    violations.append(
                        f"{src.relative_to(ROOT)} in '{ctx}' imports "
                        f"entities from '{imported_ctx}': {mod}. "
                        "Adapters must not cross bounded context boundaries "
                        "for entity types."
                    )

    assert not violations, (
        "Infrastructure adapters must not import entities from other "
        "bounded contexts:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
