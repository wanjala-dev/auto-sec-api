#!/bin/bash
# Fetch a fresh JWT token for the Wanjala MCP server.
# Requires SUPER_USER_PASSWORD and optionally MCP_USER_EMAIL in the environment.

MCP_USER_EMAIL="${MCP_USER_EMAIL:-henry@wanjala.art}"

if [ -z "$SUPER_USER_PASSWORD" ]; then
  echo "ERROR: SUPER_USER_PASSWORD is not set." >&2
  exit 1
fi

curl -s -X POST http://localhost:8010/users/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email": "'"$MCP_USER_EMAIL"'", "password": "'"$SUPER_USER_PASSWORD"'"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["tokens"]["access"])'
