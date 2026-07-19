#!/usr/bin/env bash
# Stop hook (runs async, re-wakes on failure): after Claude stops, if Python files
# changed AND the Docker web container is up, run the suite. On failure, exit 2 so the
# failing tail is fed back into the session for Claude to fix.
#
# Guards (deliberate):
#   * Only runs when tracked/untracked *.py actually changed — never on doc-only stops.
#   * Only runs when compose-web-1 is up. Per CLAUDE.md the suite MUST run inside the
#     Docker web container (the DJANGO_SETTINGS_MODULE trap); if it isn't up we do
#     nothing rather than pollute the dev Postgres.
set -uo pipefail

# The Django project (and its Makefile with the `test` target) is the app dir
# (api-v2.0/), which is NOT the git toplevel here — the repo root is a parent of it.
# Prefer CLAUDE_PROJECT_DIR (the app dir Claude was launched in); fall back to git top.
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$root" ] || exit 0
cd "$root" || exit 0

# Manual kill-switch: `touch .claude/.stop-tests-disabled` to silence this hook — e.g.
# while a feature branch is intentionally dirty / mid-work and the full suite would just
# surface unrelated WIP failures on every stop. `rm .claude/.stop-tests-disabled` to re-enable.
[ -f "$root/.claude/.stop-tests-disabled" ] && exit 0

# No `test` target reachable here (e.g. cd landed above the app dir) → no-op, don't error.
make -n test >/dev/null 2>&1 || exit 0

# Only proceed when Python changed. git porcelain lines look like " M path" / "?? path"
# (paths with spaces are quoted, so allow an optional trailing quote before EOL).
if ! git status --porcelain 2>/dev/null | grep -qE '\.py"?$'; then
  exit 0
fi

# Tests must run inside the Docker web container. If it's down, no-op.
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'compose-web-1'; then
  exit 0
fi

out=$(make test 2>&1); status=$?
[ "$status" -eq 0 ] && exit 0

printf 'Test suite failed after your changes (make test). Last 60 lines:\n\n%s\n' \
  "$(printf '%s\n' "$out" | tail -n 60)" >&2
exit 2
