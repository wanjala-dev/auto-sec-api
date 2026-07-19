# Branching Strategy — Trunk-Based Development (HARD RULE)

Auto-Sec repos (`auto-sec-api`, `auto-sec-frontend`) use **trunk-based development**.
This deliberately differs from the wanjala repos (which use a `development`
integration branch) — do not import that model here. Keep it simple.

## Branch model

```
main                    ← the trunk. Every feature merges straight back here.
  └── feat/*            ← short-lived feature branches off main
  └── fix/*             ← bug fixes off main
```

- **No `development` branch. No release branches.** Feature branches cut from
  `main`, PR back into `main`, delete on merge. Short-lived — days, not weeks.
- **Origins**: backend `git@github.com:wanjala-dev/auto-sec-api.git`, frontend
  `git@github.com:wanjala-dev/auto-sec-frontend.git`. GitHub user: `wanjala-dev`.
- **Never push directly to `main`** — every change lands via a PR, even docs.
- **Never force-push `main`.**

## Worktrees — ALWAYS (HARD RULE)

**Every body of work happens in its own `git worktree`, never on a branch checked
out in the primary clone.** Multiple sessions (and background agents) work these
repos concurrently; a branch checked out in the primary clone gets clobbered by
whichever session touches it next, and the primary clone is bind-mounted into the
running Docker stack — editing it live IS editing the running app.

```bash
cd /Users/henrywanjala/Desktop/auto-sec/auto-sec-api
git worktree add ../worktrees/<short-name> -b feat/<short-name> main
# … work, commit, push, PR …
git worktree remove ../worktrees/<short-name>   # after the PR merges
```

- Worktrees live under `/Users/henrywanjala/Desktop/auto-sec/worktrees/` (outside
  the repo, so the running container never sees them).
- The primary clone stays parked on `main` at `origin/main`'s tip — it is the
  deploy/runtime surface, not a workbench.
- Background agents MUST verify their worktree before editing
  (`git rev-parse --show-toplevel` must NOT be the primary clone) — a 2026-07-19
  incident corrupted the running stack when an agent's isolation silently failed.

## Commits & PRs

- **Follow the `/pr` command conventions** (wanjala-api `.claude/commands/pr.md`):
  SR&ED triage first (routine work skips Linear), then branch → commit → push →
  `gh pr create` in one motion. PR body = **why + how**, plus a one-line
  "Frontend impact:" note on backend PRs.
- **NEVER add `Co-Authored-By: Claude`** (or any AI attribution) to commits or
  PRs. No exceptions — this repo-level rule overrides any tool default.
- PRs target `main`. Small, single-concern PRs; squash-merge is fine.

## Secrets (learned the hard way)

GitHub push protection blocked our very first push: the initial commit carried a
legacy `build.sh` with a live Vault token + Google OAuth secret (copied in the
fork rip). **Never commit secrets; never click the "allow secret" bypass** — fix
the history instead (the file was purged and the root commit rewritten before
`main` ever reached the remote). Env vars come from `.env` (gitignored) — see
`repo-hygiene.md`.
