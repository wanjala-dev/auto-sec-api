"""Architecture guardrail: management commands that use the component layer
must go through the application/facade boundary — not directly into
infrastructure or repositories.

A command is considered "migrated" if it imports from ``components.*`` or
``facades.*``.  Once migrated, it must not also reach around the
application layer into:

- ``components.*.infrastructure.*``
- ``components.*.domain.*`` (except shared_kernel value objects / enums)

Un-migrated commands (pure ``apps.*`` / Django only) are **not** flagged
here — they remain legacy and will be addressed in later phases.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = ROOT / "apps"


def _iter_management_commands() -> list[Path]:
    """Yield all ``management/commands/*.py`` files under apps/."""
    commands: list[Path] = []
    for cmd_dir in APPS_DIR.rglob("management/commands"):
        if not cmd_dir.is_dir():
            continue
        for f in sorted(cmd_dir.glob("*.py")):
            if f.is_file() and f.name != "__init__.py":
                commands.append(f)
    return commands


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


def _is_migrated(modules: set[str]) -> bool:
    """A command is 'migrated' if it imports from components.* or facades.*."""
    return any(
        m.startswith("components.") or m.startswith("facades.")
        for m in modules
    )


def test_migrated_management_commands_use_application_boundary():
    """Migrated commands must not bypass the application/facade layer.

    If a management command imports from ``components.*`` or ``facades.*``
    it is considered migrated.  Once migrated, it must NOT import from:

    - ``components.<ctx>.infrastructure.*``
    - ``components.<ctx>.domain.*``  (shared_kernel exempt)

    It SHOULD import from:

    - ``components.<ctx>.application.*``
    - ``components.<ctx>.api.*``
    - ``facades.*``
    """
    violations: list[str] = []

    for cmd_file in _iter_management_commands():
        modules = _imported_modules(cmd_file)
        if not _is_migrated(modules):
            continue  # legacy, not our concern yet

        for mod in modules:
            if not mod.startswith("components."):
                continue
            parts = mod.split(".")
            if len(parts) < 3:
                continue
            ctx = parts[1]
            layer = parts[2]

            # shared_kernel is always allowed
            if ctx == "shared_kernel":
                continue

            if layer == "infrastructure":
                violations.append(
                    f"{cmd_file.relative_to(ROOT)} is migrated but imports "
                    f"infrastructure directly: {mod}. "
                    "Use a provider or facade instead."
                )
            elif layer == "domain":
                violations.append(
                    f"{cmd_file.relative_to(ROOT)} is migrated but imports "
                    f"domain directly: {mod}. "
                    "Use a provider or application service instead."
                )

    assert not violations, (
        "Migrated management commands must not bypass the application boundary:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
