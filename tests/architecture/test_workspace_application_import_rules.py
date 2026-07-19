import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_APPLICATION_DIR = ROOT / "components" / "workspace" / "application"
BANNED_PREFIXES = {
    "apps",
    "django",
    "rest_framework",
    "stripe",
    "celery",
    "requests",
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


def test_workspace_application_modules_are_framework_and_app_import_free_except_documented_transitional_file():
    for source_file in _iter_python_files(WORKSPACE_APPLICATION_DIR):
        if source_file.name == "__init__.py":
            continue
        imported_modules = _imported_modules(source_file)
        banned = sorted(
            module for module in imported_modules if module.split(".", 1)[0] in BANNED_PREFIXES
        )
        assert not banned, f"{source_file} imports banned modules inside workspace application: {banned}"
