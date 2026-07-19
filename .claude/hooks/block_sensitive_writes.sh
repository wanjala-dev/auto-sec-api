#!/usr/bin/env bash
# PreToolUse (Write|Edit): block edits to secrets / VCS internals BEFORE they happen.
# Blocking = exit 2 with a message on stderr (same convention as the git-push guard
# in .claude/settings.json). Non-matching paths exit 0 and the write proceeds.
set -uo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file_path" ] && exit 0

base=$(basename "$file_path")

block() {
  echo "BLOCKED: $1" >&2
  echo "If this is intentional, edit the file yourself or adjust .claude/hooks/block_sensitive_writes.sh." >&2
  exit 2
}

# VCS internals — never let a tool write into .git/
case "$file_path" in
  */.git/*|.git/*) block "writes into a .git/ directory are not allowed ($file_path)." ;;
esac

# Secrets / credentials by filename
case "$base" in
  .env|.env.*|*.env)   block "$base is an environment/secrets file (.env family)." ;;
  *.pem|*.key|*.p12|*.pfx|*.keystore|id_rsa|id_ed25519|id_dsa|id_ecdsa)
                       block "$base looks like a private key / credential file." ;;
  .npmrc|.pypirc|.netrc|credentials)
                       block "$base commonly holds credentials/tokens." ;;
esac

# Credential directories
case "$file_path" in
  */.aws/*|*/.ssh/*|*/.gnupg/*)
    block "writes into a credentials directory are not allowed ($file_path)." ;;
esac

exit 0
