---
description: Repository hygiene — file organization, documentation placement, no stray files
globs: "**/*"
alwaysApply: true
---

# Repository Hygiene

## 1. Documentation Placement

**All documentation MUST go in `docs/`**, organized by topic. Never place docs at the repo root or inside component directories.

```
# CORRECT
docs/architecture/CAMPAIGNS_ARCHITECTURE.md
docs/adr/0004-new-decision.md
docs/plans/feature-x-plan.md

# WRONG — root litter
PAYMENT_SOURCE_TYPE_GUIDE.md
MIGRATION_PLAN.md
TODO.md

# WRONG — docs inside components
components/commerce/CQRS_QUICK_REFERENCE.md
components/campaigns/ARCHITECTURE.md
components/MIGRATION_SUMMARY.txt
```

**Allowed root-level files** (exhaustive list):
- `CLAUDE.md` — Claude Code instructions
- `AGENTS.md` — Agent workspace rules
- `README.md` — Project readme
- `requirements/` — Python dependencies
- `pyproject.toml`, `pytest.ini`, `setup.cfg` — Tool config
- `manage.py`, `Dockerfile` — Infrastructure (the k8s Kustomize stack lives in the separate
  `auto-sec-infra` repo, not here; compose was retired 2026-07-26)
- `.env*` — Environment config

Everything else goes in `docs/` under the appropriate subdirectory:
- `docs/adr/` — Architecture Decision Records
- `docs/architecture/` — Architecture guides and diagrams
- `docs/plans/` — Implementation roadmaps
- `docs/checklists/` — Migration and refactoring checklists
- `docs/frontend-handoffs/` — API contract documents for frontend
- `docs/reference/` — Reference implementations
- `docs/reviews/` — Code review standards

## 2. No Stray Files

- No `.txt` or `.md` files inside `components/` (except `__init__.py`)
- No `TODO.md`, `NOTES.md`, `SCRATCH.md` anywhere outside `docs/`
- No generated reports or summaries outside `docs/`
- Temporary files go in `.gitignore`-d directories

## 4. Test & browser artifacts NEVER land in the repo (HARD RULE)

Screenshots, accessibility snapshots, traces, videos, HARs, downloaded files — anything a
browser-automation or test run produces — go to the MCP's `--output-dir`
(`~/Desktop/claude-smoke`) or the session scratchpad. **Never the repo, and never the repo
root.**

### Where they must go

| Producer | Destination |
|---|---|
| Playwright **MCP** (`browser_take_screenshot`, `browser_snapshot`) | Pass an **absolute** path under the configured `--output-dir`. A bare `filename` resolves against the CWD — which is the repo — not the output dir. This is the trap. |
| Playwright driven via **Bash / Node** (the qa-agent pattern) | An absolute path under the scratchpad. Never a relative path, because the CWD is a worktree. |
| pytest / harness output | `tests/qa/test-results/`, already gitignored. |

### Why this is a rule and not a preference

On 2026-08-12 the repo root held **59 untracked artifacts** — `.jpeg` screenshots and
`hud-snap*.yml` snapshots — accumulated over weeks. `.gitignore` already carried a guard
written for exactly this: `/*.png`.

**It matched nothing.** Playwright MCP writes `.jpeg` by default and dumps accessibility
snapshots as `.yml`. The guard had been silently useless since the day it was written, and
nobody noticed because an ignored file and an unmatched file look identical in
`git status` — both simply absent from the staged set.

Two lessons, both general:

1. **Match the artifact SHAPE, not one guessed extension.** The `.gitignore` block now
   covers png/jpeg/jpg/webp/gif/pdf/har/zip plus the snapshot YAML patterns.
2. **`.gitignore` is a BACKSTOP, not the fix.** It stops a commit; it does not stop the
   litter. The fix is writing the artifact somewhere else in the first place. A repo root
   full of ignored junk is still a repo root full of junk — and it is how a real file gets
   lost in the noise, or swept in by a careless `git add -A`.

### The check

If `git status` at the repo root shows artifacts you did not intend to author, do not
`git add` around them and do not extend `.gitignore` to paper over it. Find the producer
and point it somewhere else.

---

## 3. ORM Models Location

All Django ORM models live in `infrastructure/persistence/`, never inside `components/`. See the **persistence-and-orm** rule for full details on model access boundaries, field ordering, and migrations.
