# Verify, Don't Guess — Ground Uncertainty in Research + the Architecture (HARD RULE)

autosec is a **fork** (see CLAUDE.md "Provenance — this is a FORK"). Unfamiliar or off-feeling
code is often **fork-drift**, not intent — so when something feels *forgy* (uncertain, hazy, or
"wait, why is it like this?"), the failure mode is to **guess and then build on the guess**. Don't.
Stop and ground it first. Guessing on a fork is how a stale assumption becomes a shipped defect.

## When something feels off, before you act

1. **Load the architecture skill + consult the ADRs and rules — before ANY structural change.**
   `.claude/skills/architecture/SKILL.md` (the CNAPP hub-and-spoke target + the C1–C7
   component-decoupling rules), `.claude/rules/architecture-manifesto.md`,
   `.claude/rules/bounded-context-structure.md`, and the relevant `docs/adr/`. **Respect Explicit
   Architecture:** a change that "works" but breaks a boundary — a cross-context infrastructure
   import, a per-pillar finding table, a scanner that isn't a `ScannerPort` driven adapter — is a
   regression, not a feature.
2. **Research non-trivial tech / design / infra / security choices online + via connected MCPs —
   don't reason from the codebase alone.** Infra patterns (a Celery pool, a k8s idiom), library
   behaviour (LangChain, Stripe), security posture — ground them in current docs/best-practice
   first, and use ultrathink on the hard ones. (Codified after a Celery `--pool threads` config was
   chosen without research; the research showed it silently disables `soft_time_limit` and drops
   prefork's task isolation — the wrong default for a security tool. The reflex was already a
   standing preference; this makes it a rule.)
3. **Verify against the live system + the real code — not memory or a stale doc.** grep the actual
   call sites, query the cluster (`kubectl -n autosec …`), read the ADR. Plan docs and code comments
   drift from the code on a fast-moving fork. Prove the thing behaves as you think **before**
   extending it, and verify under *sustained / realistic* conditions, not a single quick pass
   (a worker that drains a queue once may OOM on the next cycle).
4. **If still unsure whether something is fork-drift vs. intent, ask — don't assume.** Name what you
   checked and what's still ambiguous.

## Why this rule exists

A fork carries the source's assumptions until each is examined; every one you don't verify is a
landmine. The cost of grounding — minutes of research, a grep, a `kubectl` check — is always less
than the cost of shipping a guess and untangling it later. This is the epistemic sibling of
`no-shortcuts.md`: that rule says *build the robust fix*; this one says *first make sure you
understand what you're fixing.*

## Cross-references

- `no-shortcuts.md` — do the robust fix; "it works" ≠ "it's correct".
- `dry-reuse.md` — grep before you build.
- `.claude/skills/architecture/SKILL.md` — the architecture to respect (load before structural work).
- CLAUDE.md — "Provenance — this is a FORK" + "How to self-correct when the fork bites".
