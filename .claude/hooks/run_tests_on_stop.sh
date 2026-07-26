#!/usr/bin/env bash
# Stop hook (runs async, re-wakes on failure): after Claude stops, if Python files changed,
# run the architecture fitness suite in a THROWAWAY container built from the k8s app image
# (`autosec-api:local`). `api.settings.test` uses SQLite, so the suite needs no cluster/DB —
# and mounting the worktree over /app tests THIS branch's code, not the deployed image. On
# failure, exit 2 so the failing tail is fed back into the session for Claude to fix.
#
# Guards (deliberate):
#   * Only runs when tracked/untracked *.py actually changed — never on doc-only stops.
#   * Only runs when the `autosec-api:local` image exists; else no-op (nothing to run in).
#   * Kill-switch: `touch .claude/.stop-tests-disabled` to silence (e.g. mid-WIP on a dirty
#     branch where the suite would surface unrelated failures). `rm` it to re-enable.
#
# Scope: tests/architecture/ (the import-boundary fitness functions) — fast (~30s) and the
# highest-value guard in this Explicit-Architecture codebase. Run the full suite by hand.
set -uo pipefail

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$root" ] || exit 0
cd "$root" || exit 0

[ -f "$root/.claude/.stop-tests-disabled" ] && exit 0

# Only proceed when Python changed. git porcelain lines look like " M path" / "?? path"
# (paths with spaces are quoted, so allow an optional trailing quote before EOL).
if ! git status --porcelain 2>/dev/null | grep -qE '\.py"?$'; then
  exit 0
fi

# Tests run in a throwaway container from the k8s app image (built per k8s/local-image.Dockerfile
# in auto-sec-infra). If it isn't built, no-op rather than error.
if ! docker image inspect autosec-api:local >/dev/null 2>&1; then
  exit 0
fi

out=$(docker run --rm -v "$root":/app -w /app \
  --entrypoint python -e DJANGO_SETTINGS_MODULE=api.settings.test \
  autosec-api:local -m pytest -q -p no:cacheprovider tests/architecture/ 2>&1); status=$?
[ "$status" -eq 0 ] && exit 0

printf 'Architecture suite failed after your changes. Last 60 lines:\n\n%s\n' \
  "$(printf '%s\n' "$out" | tail -n 60)" >&2
exit 2
