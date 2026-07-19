from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"
FACADE_DIRS = [
    ROOT / "components" / "sponsorship" / "application" / "facades",
    ROOT / "components" / "workspace" / "application" / "facades",
]


def _iter_component_files(relative_glob: str):
    return sorted(
        path
        for path in COMPONENTS_DIR.glob(relative_glob)
        if path.is_file() and path.name != "__init__.py" and "shared_kernel" not in path.parts
    )


def test_application_dto_files_use_dto_suffix():
    for path in _iter_component_files("*/application/dto/*.py"):
        assert path.name.endswith("_dto.py"), f"{path} must end with _dto.py"


def test_application_handler_files_use_handler_or_service_suffix():
    for path in _iter_component_files("*/application/handlers/*.py"):
        assert path.name.endswith(("_handler.py", "_service.py")), (
            f"{path} must end with _handler.py or _service.py"
        )


def test_application_query_files_use_query_suffix():
    for path in _iter_component_files("*/application/queries/*.py"):
        assert path.name.endswith("_query.py"), f"{path} must end with _query.py"


def test_domain_entity_files_use_entity_suffix():
    for path in _iter_component_files("*/domain/entities/*.py"):
        assert path.name.endswith("_entity.py"), f"{path} must end with _entity.py"


def test_application_root_service_files_use_service_suffix():
    for path in _iter_component_files("*/application/*.py"):
        if "facades" in path.parts:
            continue  # facades use _facade.py suffix (validated separately)
        # Convention: bare service.py is allowed (one per context)
        assert path.name == "service.py" or path.name.endswith("_service.py"), (
            f"{path} must be service.py or end with _service.py"
        )


def test_infrastructure_repository_files_use_repository_suffix():
    for path in _iter_component_files("*/infrastructure/repositories/*.py"):
        assert path.name.endswith("_repository.py"), f"{path} must end with _repository.py"


def test_port_files_use_port_suffix():
    for path in _iter_component_files("*/ports/*.py"):
        assert path.name.endswith("_port.py"), f"{path} must end with _port.py"


def test_component_port_files_do_not_mix_repository_and_port_terms():
    # Transitional: existing *_repository_port.py files are allowed until the
    # bulk rename to *_store_port.py / *_reader_port.py is completed.
    _ALLOWED_REPOSITORY_PORTS = {
        "user_repository_port.py",
        "store_repository_port.py",
        "product_repository_port.py",
        "cart_repository_port.py",
        "notification_repository_port.py",
        "file_repository_port.py",
        "conversation_repository_port.py",
    }
    for path in _iter_component_files("*/ports/*.py"):
        if path.name in _ALLOWED_REPOSITORY_PORTS:
            continue
        assert not path.name.endswith("_repository_port.py"), (
            f"{path} mixes repository and port concepts in one filename"
        )


def test_facade_files_use_facade_suffix():
    for facade_dir in FACADE_DIRS:
        for path in sorted(facade_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            assert path.name.endswith("_facade.py"), f"{path} must end with _facade.py"


def test_domain_entities_do_not_import_django():
    for path in _iter_component_files("*/domain/entities/*.py"):
        source = path.read_text()
        assert "from django" not in source and "import django" not in source, (
            f"{path} must not import Django in domain entities"
        )


def test_application_and_infra_raise_domain_errors_not_builtins():
    """Application and infrastructure layers must raise domain errors, not builtins.

    Detects ``raise ValueError(...)`` and ``raise PermissionError(...)`` in
    application use cases, queries, services, providers, and infrastructure
    repositories/services. These should be replaced with domain-specific
    error classes from the shared taxonomy.

    An allowlist covers known false positives (e.g., re-raises inside
    ``except`` blocks that catch third-party exceptions).
    """
    import ast
    import re

    BANNED_BUILTINS = {"ValueError", "PermissionError"}

    # Patterns that scan for top-level application/infra directories
    GLOBS = [
        "*/application/**/*.py",
        "*/infrastructure/**/*.py",
    ]

    # Transitional allowlist: agents and infrastructure-heavy contexts still
    # use bare ValueError/PermissionError. Track prefixes here; remove
    # entries as each context migrates to domain errors.
    ALLOWLIST_PREFIXES = (
        "components/agents/infrastructure/",
        "components/budgeting/infrastructure/adapters/imports.py",
        "components/knowledge/infrastructure/",
        "components/notifications/infrastructure/",
        "components/payments/infrastructure/adapters/",
        "components/shared_platform/infrastructure/",
        "components/sponsorship/infrastructure/repositories/donation_payment_repository.py",
        "components/workspace/infrastructure/adapters/aggregation_service.py",
    )
    ALLOWLIST: set[str] = set()

    violations = []
    for glob_pattern in GLOBS:
        for path in sorted(COMPONENTS_DIR.glob(glob_pattern)):
            if not path.is_file() or path.name == "__init__.py":
                continue
            if "shared_kernel" in path.parts:
                continue
            relative = path.relative_to(ROOT)
            relative_str = str(relative)
            if relative_str in ALLOWLIST:
                continue
            if any(relative_str.startswith(p) for p in ALLOWLIST_PREFIXES):
                continue

            source = path.read_text()
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and node.exc is not None:
                    exc = node.exc
                    name = None
                    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                        name = exc.func.id
                    elif isinstance(exc, ast.Name):
                        name = exc.id
                    if name in BANNED_BUILTINS:
                        violations.append(f"{relative}:{node.lineno} raises {name}")

    assert not violations, (
        "Application/infrastructure layers must use domain-specific errors "
        "from the shared taxonomy instead of bare builtins:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_api_request_files_use_request_suffix():
    """Files in api/requests/ must end with _request.py or _requests.py.

    Transitional: some legacy contexts have files without the suffix
    (e.g., content/, notifications/). These are tracked in the allowlist
    and should be renamed when those contexts are next refactored.
    """
    _ALLOWED_LEGACY_REQUEST_FILES = {
        # content context — legacy naming, rename on next refactor
        "category.py",
        "comment.py",
        "news.py",
        # notifications context — legacy naming, rename on next refactor
        "ai_preference.py",
        "notification.py",
        "user_preference.py",
        "workspace_preference.py",
    }
    for path in _iter_component_files("*/api/requests/*.py"):
        if path.name in _ALLOWED_LEGACY_REQUEST_FILES:
            continue
        assert path.name.endswith(("_request.py", "_requests.py")), (
            f"{path} must end with _request.py or _requests.py"
        )


def test_api_resource_files_use_resource_suffix():
    """Files in api/resources/ must end with _resource.py or _resources.py.

    Transitional: some legacy contexts have files without the suffix
    (e.g., content/, notifications/). These are tracked in the allowlist
    and should be renamed when those contexts are next refactored.
    """
    _ALLOWED_LEGACY_RESOURCE_FILES = {
        # content context — legacy naming, rename on next refactor
        "category.py",
        "comment.py",
        "news.py",
        # notifications context — legacy naming, rename on next refactor
        "ai_preference.py",
        "notification.py",
        "user_preference.py",
        "workspace_preference.py",
    }
    for path in _iter_component_files("*/api/resources/*.py"):
        if path.name in _ALLOWED_LEGACY_RESOURCE_FILES:
            continue
        assert path.name.endswith(("_resource.py", "_resources.py")), (
            f"{path} must end with _resource.py or _resources.py"
        )


def test_domain_errors_extend_shared_taxonomy():
    """Component domain error base classes must extend the shared kernel taxonomy.

    Every ``domain/errors.py`` file in a non-shared_kernel component must
    import at least one base from ``components.shared_kernel.domain.errors``.
    This ensures uniform HTTP mapping and catch-at-taxonomy-level semantics.
    """
    import ast

    for path in sorted(COMPONENTS_DIR.glob("*/domain/errors.py")):
        if "shared_kernel" in path.parts:
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        imports_shared = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("components.shared_kernel.domain.errors"):
                    imports_shared = True
                    break
        assert imports_shared, (
            f"{path} must import from components.shared_kernel.domain.errors "
            "so domain exceptions follow the shared taxonomy"
        )
