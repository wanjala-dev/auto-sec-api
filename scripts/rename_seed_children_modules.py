#!/usr/bin/env python3
"""Codemod: rename legacy module/app references.

This repo historically used "seed" (organization/workspace) and "children"
(sponsorship recipients). We are moving to:

- apps.workspaces -> apps.workspaces
- seed (app label) -> workspaces
- apps.sponsorship.recipients -> apps.sponsorship.recipients
- children (app label) -> recipients

This script intentionally focuses on import paths and Django app labels so the
codebase can load under the new module names. It does not attempt to rename the
underlying model class names or database tables; those can be handled as a
separate, more semantic refactor.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest-dbs",
    "venv",
    "media",
    "test-media",
    "static",
    "static-test",
    "logs",
}


@dataclass(frozen=True)
class Replacement:
    old: str
    new: str


REPLACEMENTS: tuple[Replacement, ...] = (
    Replacement("infrastructure.workspaces.", "infrastructure.workspaces."),
    Replacement("infrastructure.workspaces", "infrastructure.workspaces"),
    Replacement("infrastructure.sponsorship.recipients.", "infrastructure.sponsorship.recipients."),
    Replacement("infrastructure.sponsorship.recipients", "infrastructure.sponsorship.recipients"),
    Replacement('get_model("workspaces",', 'get_model("workspaces",'),
    Replacement("get_model('workspaces',", "get_model('workspaces',"),
    Replacement('get_model("recipients",', 'get_model("recipients",'),
    Replacement("get_model('recipients',", "get_model('recipients',"),
    # Common Django model string refs and migration `to=` targets.
    Replacement("'workspaces.", "'workspaces."),
    Replacement('"workspaces.', '"workspaces.'),
    Replacement("('workspaces',", "('workspaces',"),
    Replacement('("workspaces",', '("workspaces",'),
    Replacement("'recipients.", "'recipients."),
    Replacement('"recipients.', '"recipients.'),
    Replacement("('recipients',", "('recipients',"),
    Replacement('("recipients",', '("recipients",'),
)


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS or part.startswith(".venv") for part in path.parts):
            continue
        files.append(path)
    return files


def apply_replacements(text: str) -> tuple[str, int]:
    updated = text
    changes = 0
    for repl in REPLACEMENTS:
        if repl.old in updated:
            occurrences = updated.count(repl.old)
            updated = updated.replace(repl.old, repl.new)
            changes += occurrences
    return updated, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk (default: dry run).",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    python_files = iter_python_files(root)

    touched = 0
    total_changes = 0
    for path in python_files:
        original = path.read_text(encoding="utf-8")
        updated, changes = apply_replacements(original)
        if not changes:
            continue
        touched += 1
        total_changes += changes
        if args.apply:
            path.write_text(updated, encoding="utf-8")
        else:
            print(f"{path}: {changes} replacements")

    action = "Applied" if args.apply else "Planned"
    print(f"{action} {total_changes} replacements across {touched} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
