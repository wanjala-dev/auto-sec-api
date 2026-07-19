"""Architecture guardrail: Shared Platform bounded context import rules.

Ensures that the domain, application, and port layers in components/shared_platform/
remain framework-free — no Django, DRF, Celery, or direct apps.* imports.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SHARED_PLATFORM_DOMAIN_DIR = ROOT / "components" / "shared_platform" / "domain"
SHARED_PLATFORM_APPLICATION_DIR = ROOT / "components" / "shared_platform" / "application"

BANNED_PREFIXES = {
    "apps",
    "django",
    "rest_framework",
    "celery",
    "requests",
    "stripe",
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
            f"inside shared_platform {layer_name}: {banned}"
        )


def test_shared_platform_domain_is_framework_free():
    _check_layer(SHARED_PLATFORM_DOMAIN_DIR, "domain")


def test_shared_platform_application_is_framework_free():
    _check_layer(SHARED_PLATFORM_APPLICATION_DIR, "application")


def test_shared_platform_ports_are_framework_free():
    ports_dir = ROOT / "components" / "shared_platform" / "ports"
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
            f"inside shared_platform ports: {banned}"
        )


def test_shared_platform_domain_does_not_import_infrastructure():
    for source_file in _iter_python_files(SHARED_PLATFORM_DOMAIN_DIR):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        infra_imports = sorted(
            module for module in imported_modules if "infrastructure" in module
        )
        assert not infra_imports, (
            f"{source_file.relative_to(ROOT)} imports infrastructure "
            f"from domain layer: {infra_imports}"
        )
