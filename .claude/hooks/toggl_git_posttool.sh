#!/usr/bin/env bash
# SR&ED auto time-tracking — react to git/gh commands (PostToolUse on Bash).
#   git worktree add / checkout -b / switch -c for a feat/SEE-* branch → start a timer for that ticket
#   git checkout / switch to an existing branch                        → start if that branch is a SEE one
#   gh pr create                                                       → stop the running auto timer
# Cheap: only the matched commands touch the network; everything else exits immediately.
TOGGL="/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0/.claude/tools/toggl.py"
input=$(cat)
# Cheap pure-bash pre-filter: skip (no Python spawn) unless the raw payload mentions a git/gh
# command we care about. This runs on EVERY Bash tool call, so it must stay fast.
case "$input" in
  *"gh pr create"*|*"git worktree add"*|*"git checkout"*|*"git switch"*) ;;
  *) exit 0 ;;
esac
# Matched — now extract the exact command so we don't act on a coincidental substring in an arg.
cmd=$(printf '%s' "$input" | python3 -c "import sys,json
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('command',''))
except Exception:
    pass" 2>/dev/null)
[ -z "$cmd" ] && exit 0
cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null
case "$cmd" in
  *"gh pr create"*)
    python3 "$TOGGL" auto-stop >/dev/null 2>&1 || true ;;
  *"git worktree add"*|*"git checkout -b"*|*"git switch -c"*)
    # the new branch is the token after -b / -c (not the worktree path, which may also contain 'see-')
    br=$(printf '%s' "$cmd" | sed -nE 's/.*[[:space:]]-(b|c)[[:space:]]+([^[:space:]]+).*/\2/p')
    t=$(printf '%s' "$br" | grep -oiE 'see-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
    if [ -n "$t" ]; then
      python3 "$TOGGL" auto-start --ticket "$t" --branch "$br" >/dev/null 2>&1 || true
    else
      python3 "$TOGGL" auto-start >/dev/null 2>&1 || true
    fi ;;
  *"git checkout"*|*"git switch"*)
    python3 "$TOGGL" auto-start >/dev/null 2>&1 || true ;;
esac
exit 0
