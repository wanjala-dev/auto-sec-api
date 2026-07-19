#!/usr/bin/env bash
# SR&ED auto time-tracking — session boundaries.
#   SessionStart → `toggl_session.sh start`  (start a timer if resuming on a SEE branch)
#   SessionEnd   → `toggl_session.sh stop`   (close any running auto timer)
# No-ops cleanly off SEE work or when TOGGL_API_TOKEN isn't in the env.
TOGGL="/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0/.claude/tools/toggl.py"
cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null
python3 "$TOGGL" "auto-$1" >/dev/null 2>&1 || true
exit 0
