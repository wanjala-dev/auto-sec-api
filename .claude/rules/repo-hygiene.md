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
- `manage.py`, `Dockerfile`, `docker-compose*.yml` — Infrastructure
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

## 3. ORM Models Location

All Django ORM models live in `infrastructure/persistence/`, never inside `components/`. See the **persistence-and-orm** rule for full details on model access boundaries, field ordering, and migrations.
