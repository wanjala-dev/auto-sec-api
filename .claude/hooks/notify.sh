#!/usr/bin/env bash
# Notification hook: surface Claude Code notifications (permission waits, idle prompts)
# as a macOS desktop notification carrying the REAL message text. Never blocks.
set -uo pipefail

input=$(cat 2>/dev/null || true)
msg=$(printf '%s' "$input" | jq -r '.message // empty' 2>/dev/null)
[ -z "$msg" ] && msg="Claude Code needs your attention"

# Pass the message as an argv item so quotes/backticks in it can't break the AppleScript.
osascript \
  -e 'on run argv' \
  -e 'display notification (item 1 of argv) with title "Claude Code" sound name "Glass"' \
  -e 'end run' \
  "$msg" >/dev/null 2>&1 || true
