#!/usr/bin/env bash
# PreToolUse guard for SR&ED Linear linkage.
#
# Fires on `gh pr create` (scoped via the hook's `if` in .claude/settings.json).
# Blocks the PR ONLY when it touches SR&ED-eligible paths AND carries no Linear
# `SEE-<n>` link — so routine PRs are never nagged, but R&D work can't land
# unlinked. Exit 2 + a stderr message is fed back to Claude as guidance.
#
# Override for genuinely-routine work: put `Linear: none` (or `[no-sred]`) in the
# PR body. See .claude/rules/sred-sdlc.md.
set -uo pipefail

# --- recover the proposed command (env var first, then stdin JSON) ----------
RAW="${TOOL_INPUT:-}"
[ -z "$RAW" ] && RAW="$(cat 2>/dev/null || true)"
CMD="$(printf '%s' "$RAW" | jq -r '.command // .tool_input.command // empty' 2>/dev/null || true)"
[ -z "$CMD" ] && CMD="$RAW"

# Only guard PR creation (defensive; `if` already scopes this).
printf '%s' "$CMD" | grep -q "gh pr create" || exit 0

# Explicit override: author has declared this non-R&D.
printf '%s' "$CMD" | grep -qiE 'Linear:[[:space:]]*none|\[no-sred\]' && exit 0

# Already linked? (branch name OR PR title/body contains SEE-<n>)
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
printf '%s %s' "$BRANCH" "$CMD" | grep -qE 'SEE-[0-9]+' && exit 0

# --- changed files vs the integration base ---------------------------------
BASE="$(git merge-base HEAD origin/development 2>/dev/null \
      || git merge-base HEAD origin/main 2>/dev/null || echo '')"
if [ -n "$BASE" ]; then
  FILES="$(git diff --name-only "$BASE"...HEAD 2>/dev/null || true)"
else
  FILES="$(git diff --name-only HEAD~1 2>/dev/null || true)"
fi
# Test injection point (lets the pipe-test exercise the block path deterministically).
FILES="${SRED_GUARD_FILES-$FILES}"

# R&D-eligible path heuristic (backend repo). Mirrors .claude/rules/sred-sdlc.md.
RND='components/(agents|knowledge|budgeting|content)/|infrastructure/.*(agent|knowledge|embedding|vector|rag)|reconcil|bank.?feed|plaid'
printf '%s' "$FILES" | grep -qiE "$RND" || exit 0   # routine paths → no linkage required

# R&D paths touched, no SEE- link, no override → block with guidance.
cat >&2 <<'MSG'
BLOCKED (SR&ED): this PR touches R&D-eligible paths but has no Linear ticket link.
Per .claude/rules/sred-sdlc.md, link a `seed` ticket first:
  1. Create a SEE-<n> issue via the Linear MCP in the right project,
     with sred:* (eligibility) + repo:* labels.
  2. Put the ID in the branch name AND add `Linear: SEE-<n>` to the PR body.
If this is genuinely routine (not R&D), re-run with `Linear: none` in the PR body.
MSG
exit 2
