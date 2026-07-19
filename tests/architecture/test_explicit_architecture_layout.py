from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"


def test_explicit_architecture_scaffolding_exists():
    """Anchor paths of the explicit architecture that must never disappear.

    Retuned 2026-07 for the auto-sec fork: the wanjala-only anchors
    (``components/sponsorship`` and the docs/adr + ownership-map files that
    were never ported) are dropped; the anchors below are the fork's actual
    load-bearing contexts. Add an anchor when a new context becomes
    load-bearing — don't re-add wanjala paths.
    """
    required_paths = [
        ROOT / "components",
        ROOT / "components" / "shared_kernel",
        ROOT / "components" / "workspace" / "application" / "facades",
        ROOT / "components" / "agents" / "application" / "facades",
        ROOT / "components" / "integrations" / "application" / "ports",
        ROOT / "components" / "shared_platform" / "application" / "facades",
    ]

    for path in required_paths:
        assert path.exists(), f"Expected architecture path to exist: {path}"


def _has_python_files(directory: Path) -> bool:
    """Return True if directory exists and contains at least one .py file
    that is not __init__.py."""
    if not directory.is_dir():
        return False
    return any(p.is_file() and p.suffix == ".py" and p.name != "__init__.py" for p in directory.iterdir())


def test_contexts_with_controllers_have_nonempty_request_and_resource_dirs():
    """Every bounded context that has a controller.py must also have
    non-empty api/requests/ and api/resources/ directories.

    Request DTOs (frozen dataclasses in api/requests/) translate validated
    HTTP input into typed objects for the use case layer. Resource DTOs
    (frozen dataclasses in api/resources/) translate domain entities into
    typed objects for DRF serializers to render.

    Skipping these directories and putting all translation logic in DRF
    serializers breaks the architecture's layering contract.
    """
    # Contexts that are exempt from this rule (e.g., shared_kernel has no
    # REST adapter, shared_platform may have special structure).
    EXEMPT_CONTEXTS = {"shared_kernel", "shared_platform"}

    violations = []
    for context_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not context_dir.is_dir():
            continue
        if context_dir.name in EXEMPT_CONTEXTS:
            continue

        controller = context_dir / "api" / "controller.py"
        if not controller.is_file():
            continue  # No REST adapter — nothing to check

        requests_dir = context_dir / "api" / "requests"
        resources_dir = context_dir / "api" / "resources"

        if not _has_python_files(requests_dir):
            violations.append(
                f"components/{context_dir.name}/api/requests/ is missing or empty "
                f"(context has controller.py — it needs request DTOs)"
            )
        if not _has_python_files(resources_dir):
            violations.append(
                f"components/{context_dir.name}/api/resources/ is missing or empty "
                f"(context has controller.py — it needs resource DTOs)"
            )

    assert not violations, (
        "Bounded contexts with a controller.py must have non-empty "
        "api/requests/ and api/resources/ directories.\n"
        "See DEVELOPER_GUIDE.md 'Request DTOs, Resource DTOs, and DRF Serializers' "
        "for the required data flow.\n" + "\n".join(f"  - {v}" for v in violations)
    )
