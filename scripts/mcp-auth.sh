#!/bin/bash
# Fetch a fresh JWT token for the MCP server and export it.
#
# Requires SUPER_USER_PASSWORD in the environment.
# Optionally set MCP_USER_EMAIL (defaults to henry@wanjala.art).
#
# Usage:
#   source scripts/mcp-auth.sh      # sets WANJALA_MCP_TOKEN in current shell
#   scripts/mcp-auth.sh             # prints the token to stdout

MCP_USER_EMAIL="${MCP_USER_EMAIL:-henry@wanjala.art}"

if [ -z "$SUPER_USER_PASSWORD" ]; then
  echo "ERROR: SUPER_USER_PASSWORD is not set." >&2
  return 1 2>/dev/null || exit 1
fi

TOKEN=$(curl -s -X POST http://localhost:8010/users/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "'"$MCP_USER_EMAIL"'", "password": "'"$SUPER_USER_PASSWORD"'"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tokens']['access'])" 2>/dev/null)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "None" ]; then
  echo "ERROR: Failed to fetch MCP token. Is the server running on :8010?" >&2
  return 1 2>/dev/null || exit 1
fi

export WANJALA_MCP_TOKEN="$TOKEN"

# If not sourced, print the token
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "$TOKEN"
else
  echo "WANJALA_MCP_TOKEN set (expires in ~10 days)" >&2
fi
