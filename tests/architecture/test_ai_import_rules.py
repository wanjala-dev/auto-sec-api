"""Architecture guardrail: AI bounded context import rules.

Ensures that the domain, application, and port layers in components/ai/
remain framework-free — no Django, DRF, Celery, or direct apps.* imports.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

AI_DOMAIN_DIR = ROOT / "components" / "ai" / "domain"
AI_APPLICATION_DIR = ROOT / "components" / "ai" / "application"

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
    if not directory.exists():
        return
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
            f"inside ai {layer_name}: {banned}"
        )


def test_ai_domain_is_framework_free():
    _check_layer(AI_DOMAIN_DIR, "domain")


def test_ai_application_is_framework_free():
    _check_layer(AI_APPLICATION_DIR, "application")


def test_ai_ports_are_framework_free():
    ports_dir = ROOT / "components" / "ai" / "ports"
    if not ports_dir.exists():
        return
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
            f"inside ai ports: {banned}"
        )


def test_ai_domain_does_not_import_infrastructure():
    if not AI_DOMAIN_DIR.exists():
        return
    for source_file in _iter_python_files(AI_DOMAIN_DIR):
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


def test_ai_domain_does_not_import_application():
    if not AI_DOMAIN_DIR.exists():
        return
    for source_file in _iter_python_files(AI_DOMAIN_DIR):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        app_imports = sorted(
            module for module in imported_modules if ".application." in module
        )
        assert not app_imports, (
            f"{source_file.relative_to(ROOT)} imports application "
            f"from domain layer: {app_imports}"
        )
