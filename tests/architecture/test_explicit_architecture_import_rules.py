import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"
BANNED_DOMAIN_IMPORT_PREFIXES = {
    "django",
    "rest_framework",
    "celery",
    "stripe",
    "braintree",
    "redis",
    "requests",
}


def _iter_python_files(path: Path):
    if not path.exists():
        return []
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


def test_component_domain_modules_do_not_import_frameworks():
    domain_dirs = [path for path in COMPONENTS_DIR.glob("*/domain") if path.is_dir()]

    for domain_dir in domain_dirs:
        for source_file in _iter_python_files(domain_dir):
            imported_modules = _imported_modules(source_file)
            banned = {
                module
                for module in imported_modules
                if module.split(".", 1)[0] in BANNED_DOMAIN_IMPORT_PREFIXES
            }
            assert not banned, f"{source_file} imports banned framework modules: {sorted(banned)}"


def test_shared_kernel_is_framework_free():
    """Shared kernel domain, application, and ports must be framework-free.

    The infrastructure layer is allowed to import Django/frameworks
    (it's the adapter boundary), so it is excluded from this check.
    """
    shared_kernel_dir = COMPONENTS_DIR / "shared_kernel"

    # Only scan layers that must be framework-free
    framework_free_layers = ["domain", "application", "ports"]

    for layer in framework_free_layers:
        layer_dir = shared_kernel_dir / layer
        for source_file in _iter_python_files(layer_dir):
            imported_modules = _imported_modules(source_file)
            banned = {
                module
                for module in imported_modules
                if module.split(".", 1)[0] in BANNED_DOMAIN_IMPORT_PREFIXES
            }
            assert not banned, f"{source_file} imports banned framework modules: {sorted(banned)}"


def test_component_application_modules_do_not_import_views():
    application_dirs = [path for path in COMPONENTS_DIR.glob("*/application") if path.is_dir()]

    for application_dir in application_dirs:
        for source_file in _iter_python_files(application_dir):
            imported_modules = _imported_modules(source_file)
            banned = sorted(
                module
                for module in imported_modules
                if module.endswith(".views") or ".views." in module
            )
            assert not banned, f"{source_file} imports view modules from outside the application core: {banned}"
