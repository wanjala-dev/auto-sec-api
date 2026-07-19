#!/usr/bin/env bash
# PostToolUse (Write|Edit): format the file Claude just wrote/edited. Never blocks.
# Python -> ruff (this repo's formatter). Web files -> prettier only if it's on PATH
# (a no-op in this backend repo, but keeps the hook honest about "any file").
set -uo pipefail

input=$(cat)
f=$(printf '%s' "$input" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')
[ -z "$f" ] && exit 0
[ -f "$f" ] || exit 0

case "$f" in
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff format --quiet "$f"       >/dev/null 2>&1 || true
      ruff check --fix --quiet "$f"  >/dev/null 2>&1 || true
    fi
    ;;
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.scss|*.md|*.yaml|*.yml|*.html)
    if command -v prettier >/dev/null 2>&1; then
      prettier --write "$f" >/dev/null 2>&1 || true
    fi
    ;;
esac
exit 0
