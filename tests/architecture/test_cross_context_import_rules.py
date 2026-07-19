"""Architecture guardrails: cross-context and layer boundary violations.

Covers Phase 0 checklist items:
- forbid cross-context imports inside ``components/*/domain``
- forbid controllers from importing concrete adapters directly
- forbid presentation modules from importing other contexts' models directly
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# All known bounded contexts
_CONTEXTS = sorted(
    d.name
    for d in COMPONENTS_DIR.iterdir()
    if d.is_dir() and (d / "__init__.py").exists() and d.name != "shared_kernel"
)


def _iter_python_files(path: Path):
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


def _owning_context(source_file: Path) -> str | None:
    """Return the context name for a file under components/<ctx>/…."""
    try:
        rel = source_file.relative_to(COMPONENTS_DIR)
        return rel.parts[0]
    except ValueError:
        return None


def _is_reexport_shim(source_file: Path) -> bool:
    """Return True if the file is a backward-compat re-export shim."""
    text = source_file.read_text()
    return "Backward-compat shim" in text and "import *" in text


# ── Transitional allowlist: domain files that re-export enums
# from their new canonical context during migration.
_TRANSITIONAL_DOMAIN_CROSS_CONTEXT_IMPORTS: set[tuple[str, str, str]] = {
    # workspace enums re-exports team + membership enums for backward compat
    ("workspace", "components/workspace/domain/enums.py", "components.team.domain.enums"),
    ("workspace", "components/workspace/domain/enums.py", "components.membership.domain.enums"),
    # membership entities reference team enums (InvitationStatus, TeamMembershipRole/Status)
    ("membership", "components/membership/domain/entities/membership_entity.py", "components.team.domain.enums"),
    ("membership", "components/membership/domain/entities/invitation_entity.py", "components.team.domain.enums"),
}


# ── Test 1: domain layer must not import other contexts' code ─────────

def test_domain_does_not_import_other_contexts():
    """No components/<A>/domain/ file may import from components/<B>/."""
    for ctx in _CONTEXTS:
        domain_dir = COMPONENTS_DIR / ctx / "domain"
        for src in _iter_python_files(domain_dir):
            if src.name == "__init__.py":
                continue
            if _is_reexport_shim(src):
                continue
            rel_path = str(src.relative_to(ROOT))
            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) >= 2:
                    target_ctx = parts[1]
                    # Allow importing from own context and shared_kernel
                    if target_ctx != ctx and target_ctx != "shared_kernel":
                        if (ctx, rel_path, mod) in _TRANSITIONAL_DOMAIN_CROSS_CONTEXT_IMPORTS:
                            continue
                        assert False, (
                            f"{rel_path} in domain of '{ctx}' "
                            f"imports from context '{target_ctx}': {mod}"
                        )


# ── Test 2: controllers must not import concrete adapters directly ────

_TRANSITIONAL_CONTROLLER_ADAPTER_IMPORTS: set[tuple[str, str]] = {
    # Agents context — transitional, needs provider extraction
    ("agents", "components.agents.infrastructure.adapters.actions.constants"),
}


def test_controllers_do_not_import_concrete_adapters():
    """API controllers should depend on providers/ports, not concrete adapters."""
    for ctx in _CONTEXTS:
        api_dir = COMPONENTS_DIR / ctx / "api"
        for src in _iter_python_files(api_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                if ".infrastructure.adapters." in mod or ".infrastructure.repositories." in mod:
                    if (ctx, mod) in _TRANSITIONAL_CONTROLLER_ADAPTER_IMPORTS:
                        continue
                    assert False, (
                        f"{src.relative_to(ROOT)} controller imports concrete "
                        f"infrastructure directly: {mod}. "
                        "Use the provider/composition root instead."
                    )


# ── Test 3: controllers must not import another context's ORM models ──

def test_controllers_do_not_import_other_contexts_models():
    """A controller in context A must not import models owned by context B."""
    for ctx in _CONTEXTS:
        api_dir = COMPONENTS_DIR / ctx / "api"
        for src in _iter_python_files(api_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) >= 2:
                    target_ctx = parts[1]
                    # Cross-context imports in controllers are flagged if
                    # they reference models or domain entities
                    if (
                        target_ctx != ctx
                        and target_ctx != "shared_kernel"
                        and (".domain." in mod or ".models" in mod)
                    ):
                        assert False, (
                            f"{src.relative_to(ROOT)} in '{ctx}' api layer "
                            f"imports domain/models from '{target_ctx}': {mod}. "
                            "Use a facade or shared DTO instead."
                        )


# ── Test 4: ports layer must not import infrastructure ────────────────

def test_ports_do_not_import_infrastructure():
    """Port definitions must be framework-free and not reference adapters."""
    for ctx in _CONTEXTS:
        ports_dir = COMPONENTS_DIR / ctx / "ports"
        for src in _iter_python_files(ports_dir):
            if src.name == "__init__.py":
                continue
            for mod in _imported_modules(src):
                if ".infrastructure." in mod:
                    assert False, (
                        f"{src.relative_to(ROOT)} port imports infrastructure: {mod}"
                    )
