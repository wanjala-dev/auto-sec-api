#!/usr/bin/env python3
"""Codemod: rename "seed" -> "workspace" and "child/children" -> "recipient(s)".

This script is intentionally aggressive and is meant to be run during the
Seed→Workspace and Child→Recipient rename effort.

It performs text replacements in source files, including string literals, so it
can update URL paths, serializer field names, and help text alongside Python
identifiers.

Guardrails:
- Skips common generated/virtualenv/static directories.
- Protects known third-party identifiers like `django_seed`.
"""

from __future__ import annotations

import argparse
import re
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

DEFAULT_EXTS = {".py"}

PROTECTED_LITERALS: tuple[tuple[str, str], ...] = (
    ("django_seed", "__CODEMOD_PROTECT_DJANGO_SEED__"),
)


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    replacement: str


RULES: tuple[Rule, ...] = (
    # Plurals first.
    Rule(re.compile(r"\bseeds\b"), "workspaces"),
    Rule(re.compile(r"\bSeeds\b"), "Workspaces"),
    Rule(re.compile(r"\bchildren\b"), "recipients"),
    Rule(re.compile(r"\bChildren\b"), "Recipients"),
    # CamelCase prefixes (e.g. SeedCategory -> WorkspaceCategory).
    Rule(re.compile(r"\bSeed(?=[A-Z])"), "Workspace"),
    Rule(re.compile(r"\bChild(?=[A-Z])"), "Recipient"),
    # Class/type names.
    Rule(re.compile(r"\bSeed\b"), "Workspace"),
    Rule(re.compile(r"\bChild\b"), "Recipient"),
    # Common identifier prefixes/suffixes.
    Rule(re.compile(r"\bseed_"), "workspace_"),
    Rule(re.compile(r"\bSeed_"), "Workspace_"),
    Rule(re.compile(r"\bchild_"), "recipient_"),
    Rule(re.compile(r"\bChild_"), "Recipient_"),
    # Standalone words (after prefixes to avoid double work).
    Rule(re.compile(r"\bseed\b"), "workspace"),
    Rule(re.compile(r"\bchild\b"), "recipient"),
)


def iter_files(root: Path, exts: set[str]) -> list[Path]:
    if root.is_file():
        if root.suffix in exts and not any(part in SKIP_DIRS or part.startswith(".venv") for part in root.parts):
            return [root]
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS or part.startswith(".venv") for part in path.parts):
            continue
        if path.suffix not in exts:
            continue
        files.append(path)
    return files


def protect(text: str) -> str:
    for literal, token in PROTECTED_LITERALS:
        text = text.replace(literal, token)
    return text


def unprotect(text: str) -> str:
    for literal, token in PROTECTED_LITERALS:
        text = text.replace(token, literal)
    return text


def apply_rules(text: str) -> tuple[str, int]:
    updated = protect(text)
    changes = 0
    for rule in RULES:
        updated, count = rule.pattern.subn(rule.replacement, updated)
        changes += count
    updated = unprotect(updated)
    return updated, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk (default: dry run).",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=[],
        help="File extension(s) to include (e.g. --ext .py --ext .md). Defaults to .py only.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Limit processing to one or more subpaths (repeatable). Defaults to the repo root.",
    )
    args = parser.parse_args()

    exts = set(args.ext) if args.ext else set(DEFAULT_EXTS)
    repo_root = Path(__file__).resolve().parents[1]
    roots = [repo_root / p for p in args.path] if args.path else [repo_root]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            raise SystemExit(f"Path does not exist: {root}")
        files.extend(iter_files(root, exts))

    touched = 0
    total_changes = 0
    for path in files:
        original = path.read_text(encoding="utf-8")
        updated, changes = apply_rules(original)
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
