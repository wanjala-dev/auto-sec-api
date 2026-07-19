"""Architecture guardrail: Identity bounded context import rules.

Ensures that the domain and application layers in components/identity/
remain framework-free — no Django, DRF, Celery, or direct apps.* imports.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

IDENTITY_DOMAIN_DIR = ROOT / "components" / "identity" / "domain"
IDENTITY_APPLICATION_DIR = ROOT / "components" / "identity" / "application"

BANNED_PREFIXES = {
    "apps",
    "django",
    "rest_framework",
    "celery",
    "requests",
    "stripe",
    "django_otp",
}


def _iter_python_files(path: Path):
    return sorted(candidate for candidate in path.rglob("*.py") if candidate.is_file())


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


def _check_layer(directory: Path, layer_name: str):
    """Assert every non-init .py file in directory has zero banned imports."""
    for source_file in _iter_python_files(directory):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        banned = sorted(
            module
            for module in imported_modules
            if module.split(".", 1)[0] in BANNED_PREFIXES
        )
        assert not banned, (
            f"{source_file.relative_to(ROOT)} imports banned modules "
            f"inside identity {layer_name}: {banned}"
        )


def test_identity_domain_is_framework_free():
    """Domain layer must have zero Django/DRF/ORM/apps imports."""
    _check_layer(IDENTITY_DOMAIN_DIR, "domain")


def test_identity_application_is_framework_free():
    """Application layer must have zero Django/DRF/ORM/apps imports."""
    _check_layer(IDENTITY_APPLICATION_DIR, "application")


def test_identity_ports_are_framework_free():
    """Port interfaces must depend only on domain types, not infrastructure."""
    ports_dir = ROOT / "components" / "identity" / "ports"
    for source_file in _iter_python_files(ports_dir):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        banned = sorted(
            module
            for module in imported_modules
            if module.split(".", 1)[0] in BANNED_PREFIXES
        )
        assert not banned, (
            f"{source_file.relative_to(ROOT)} imports banned modules "
            f"inside identity ports: {banned}"
        )


def test_identity_infrastructure_does_not_leak_into_domain():
    """Domain layer must not import from infrastructure."""
    for source_file in _iter_python_files(IDENTITY_DOMAIN_DIR):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        infra_imports = sorted(
            module
            for module in imported_modules
            if "infrastructure" in module
        )
        assert not infra_imports, (
            f"{source_file.relative_to(ROOT)} imports infrastructure "
            f"from domain layer: {infra_imports}"
        )
