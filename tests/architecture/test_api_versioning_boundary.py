"""Architecture guardrail: API versioning must not leak below the adapter.

Versioning is a PRIMARY-ADAPTER concern. The version dimension is allowed
only in:

* ``components/<ctx>/api/**``        — controllers, request/resource DTOs
* ``components/<ctx>/mappers/rest/**`` — DRF serializers

The application layer (``use_cases/``, ``service.py``, ``ports/``) and the
domain layer (``entities/``, ``value_objects/``, ``domain/services/``) MUST
be version-blind. A ``request.version`` check in a use case couples business
rules to a transport concern; a ``DonationEntityV2`` fractures invariants
across versions. Both are the smell this test fails the build for.

See the ``api-versioning`` skill §0 rule 2 + §7, and ADR 0006.
"""

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# Layers that MUST stay version-blind, scanned per bounded context.
_FORBIDDEN_LAYERS = ("application", "domain")

# Version-suffixed class names (e.g. DonationEntityV1, CreateDonationCommandV2)
# below the adapter mean a contract version leaked into the core model.
_VERSIONED_CLASS_RE = re.compile(r".+V\d+$")

_CONTEXTS = sorted(
    d.name
    for d in COMPONENTS_DIR.iterdir()
    if d.is_dir() and (d / "__init__.py").exists() and d.name != "shared_kernel"
)


def _iter_python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(f for f in path.rglob("*.py") if f.is_file())


def _scan(source_file: Path) -> list[str]:
    """Return version-leak findings for a single application/domain file."""
    findings: list[str] = []
    source = source_file.read_text()
    tree = ast.parse(source, filename=str(source_file))

    for node in ast.walk(tree):
        # `from rest_framework.versioning import ...` / `import rest_framework.versioning`
        if isinstance(node, ast.ImportFrom) and node.module and "versioning" in node.module:
            findings.append(f"imports versioning module `{node.module}`")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "rest_framework.versioning" in alias.name:
                    findings.append(f"imports versioning module `{alias.name}`")

        # `request.version` / `request.versioning_scheme` attribute access
        elif isinstance(node, ast.Attribute) and node.attr in {"version", "versioning_scheme"}:
            base = node.value
            if isinstance(base, ast.Name) and base.id == "request":
                findings.append(f"reads `request.{node.attr}`")

        # Version-suffixed entity/command/value-object class names
        elif isinstance(node, ast.ClassDef) and _VERSIONED_CLASS_RE.match(node.name):
            findings.append(f"defines version-suffixed class `{node.name}`")

    return findings


def test_versioning_does_not_leak_below_the_adapter():
    """No version concepts in application/ or domain/ layers.

    Allowed homes for version logic: components/<ctx>/api/** and
    components/<ctx>/mappers/rest/** only.
    """
    violations: list[str] = []

    for ctx in _CONTEXTS:
        for layer in _FORBIDDEN_LAYERS:
            for src in _iter_python_files(COMPONENTS_DIR / ctx / layer):
                if src.name == "__init__.py":
                    continue
                for finding in _scan(src):
                    violations.append(f"{src.relative_to(ROOT)} ({ctx}/{layer}): {finding}")

    assert not violations, (
        "API versioning must live only in api/ + mappers/rest/. "
        "These application/domain files leak version concepts into the core:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nTranslate at the boundary (upcast request -> canonical, downcast "
        "canonical -> versioned response) and pass the canonical shape inward. "
        "See the `api-versioning` skill."
    )
