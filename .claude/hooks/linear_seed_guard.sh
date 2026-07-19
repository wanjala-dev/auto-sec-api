#!/usr/bin/env bash
# Enforce: every Linear WRITE targets the `seed` workspace (team "Seed") and nothing
# else. The operator runs multiple Linear workspaces — a write to the wrong one is the
# failure mode this prevents. Blocks (exit 2) any save_*/create_* whose
# team / teamId / addTeams / setTeams names a team other than Seed.
# Writes with no team reference (update-by-id, comments) and all reads are allowed.
set -uo pipefail

SEED_ID="d3aa3377-ff27-43ae-b0be-95bed2df4f56"   # team "Seed", key SEE, workspace literacyseed

RAW="${TOOL_INPUT:-}"
[ -z "$RAW" ] && RAW="$(cat 2>/dev/null || true)"
INPUT="$(printf '%s' "$RAW" | jq -c '.tool_input // .' 2>/dev/null || echo "$RAW")"

# Every team reference present in this call.
REFS="$(printf '%s' "$INPUT" | jq -r '
  [ .team?, .teamId?, (.addTeams // [])[]?, (.setTeams // [])[]? ]
  | map(select(. != null and . != "")) | .[]' 2>/dev/null || true)"

[ -z "$REFS" ] && exit 0   # no team reference → update/comment/read → allow

while IFS= read -r ref; do
  [ -z "$ref" ] && continue
  lc="$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')"
  # UUID-ONLY: the team name "Seed"/"SEE" is ambiguous across workspaces (the
  # operator runs several, any could have a team named Seed). Only the team UUID
  # is unambiguous, so that is the sole accepted value.
  case "$lc" in
    "$SEED_ID") : ;;   # the seed workspace team UUID — the only allowed value
    *)
      {
        echo "BLOCKED (Linear workspace guard): refusing a Linear write targeting team '$ref'."
        echo "SR&ED Linear writes MUST pass the seed-workspace team UUID:"
        echo "    $SEED_ID   (team \"Seed\", key SEE, org literacyseed)"
        echo "A bare name like \"Seed\"/\"SEE\" is REJECTED — names are ambiguous across your"
        echo "multiple Linear workspaces. Re-issue with team/teamId = the UUID above."
      } >&2
      exit 2 ;;
  esac
done <<< "$REFS"
exit 0
