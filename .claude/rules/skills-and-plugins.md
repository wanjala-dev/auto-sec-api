# Skills & Plugins — One Source, Stamped Forks, Loud Drift (HARD RULE)

A skill is a document an agent treats as authoritative. A **stale** skill reads exactly
like a current one — same voice, same confidence, no timestamp in the agent's face. That
makes a wrong skill more dangerous than a missing one: a missing skill produces "I don't
know," a stale skill produces confident, wrong work.

## What happened (2026-08-11)

Work in this repo needed the `agents` skill — the deep-agent framework, the LangGraph
orchestrator, `RubricMiddleware`. The shared kit plugin was installed with
`scope: local` pinned to a **single unrelated project** (`frontend/literacyseed`), so the
skill was never loadable here. With nothing to load, the fallback was to grep the
filesystem, which surfaced a **986-line copy in `wanjala-api-v2.0` last touched 15 July**
— a copy containing **zero** mentions of `RubricMiddleware`, deep agents, or middleware.
The current kit version (1142 lines, 24 July) documents all of it, including the
rubric-grading convergence plan.

The result: an architecture conclusion was reached and acted on from a document that was
five weeks and one major subsystem out of date, and **nothing in the system said a word**.
A drift check across the fleet then found **21** such shadowed or diverged skill copies in
three repos.

The rule against this already existed — the kit manifest says *"never copy its skills into
a repo."* Prose enforces nothing. This rule is enforced by a script.

## The model

**Tier 1 — plugin (shared).** `wanjala-core@wanjala-kit` is the single source of truth for
engineering-craft skills across the Wanjala lineage, forks included: `agents`,
`api-versioning`, `celery-tasks`, `identity`, `logging`, `sql`, `testing`, `user-model`,
`workflow`. autosec **enables it**; autosec never copies from it.

autosec does **not** enable `wanjala-nonprofit` — those skills describe grants,
sponsorship, donations and the wanjala platform architecture: surfaces this fork
deliberately stripped. A skill describing a deleted bounded context is fork-drift with a
confident voice.

**Tier 2 — local (`.claude/skills/`).** Only for concerns that exist **here and nowhere
else**: `architecture` (the CNAPP hub-and-spoke target — autosec's own, unrelated to the
kit's wanjala platform skill), `integrations`, `personas`, `templates`, `backup-recovery`,
`gtm-qa-sweep`.

## The rules

1. **Never copy a kit skill into this repo.** Enable the plugin. A copy is a fork whose
   parent moves without telling you — which is precisely how this cost us a night.
2. **If a fork is genuinely necessary, stamp it** in the SKILL.md frontmatter so the
   divergence is a tracked fact rather than an accident:
   ```yaml
   upstream: wanjala-core/agents
   upstream_sha: 0151978202f5      # kit content hash at fork time
   forked: 2026-08-11
   why: autosec's agents code diverged at <commit>; kit examples are nonprofit-domain
   ```
   `bin/skill-drift-check.sh` in the kit then reports the moment upstream moves.
3. **A local skill must not share a name with a plugin skill this repo enables.** Two
   documents answering to one name is the ambiguity that started this.
4. **Verify provenance before trusting a skill on anything architectural.** If a skill is
   the basis for a design decision, confirm you loaded it via the plugin — not from a path
   you found by grepping. If you had to search the filesystem for a skill, that is the
   smoke alarm: the plugin isn't enabled, and whatever you found is unowned.
5. **Drift is checked automatically.** A `SessionStart` hook runs
   `wanjala-claude-kit/bin/skill-drift-check.sh` for this repo every session; shadowed or
   drifted copies are reported into context before any work begins. Do not silence it —
   fix the copy.

## Cross-references

- `verify-dont-guess.md` — ground it before building on it; a skill is exactly the kind of
  inherited document this fork must not take on faith.
- `improve-dont-replicate.md` — a copied skill is replication with a delayed fuse.
- `dry-reuse.md` — one canonical thing per concern; that includes documents.
- `/Users/henrywanjala/Desktop/wanjala-claude-kit/bin/skill-drift-check.sh` — the enforcer.
