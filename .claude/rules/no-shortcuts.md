# No Shortcuts in Recommendations (HARD RULE)

## Rule 0 — Never, ever take shortcuts. Solve once, never again. (HARDEST RULE)

Always reach for the **robust, best solution — even when it takes longer to implement.** The aim is to *solve a problem once and never again*, not to make it "work" now and pay for it later. A shortcut that passes today is a defect that comes back to bite us — in code, in architecture, in process, in recommendations. This applies to **implementation**, not just what you propose:

- **Making it "work" by side-stepping the intended design is a shortcut.** If the correct path is "route through the orchestrator" and it's not driving the behaviour yet, the fix is to *diagnose and fix the orchestrator routing* — not to bypass it with a direct call that happens to work. (Codified 2026-07-19 after switching a detector→agent delegation from the orchestrator-routed `mode=deep` to a standalone `mode=react` executor just because deep "didn't triage" — without first isolating that the real failure was an unrelated transaction bug. That is exactly the shortcut this rule forbids: work around the architecture instead of fixing why the architecture-correct path fails.)
- **Change one variable at a time.** Fixing two things at once (a bug *and* an architecture switch) so you can't tell which mattered is how a shortcut hides. Isolate, then conclude.
- **"It works" is not "it's correct."** A green result down a side-door is not proof the right path was taken. Prove the *intended* path works, or fix why it doesn't.
- **Cost/time is never a justification** for the shallow option. Estimate honestly, build the deep fix. Henry's standing instruction (2026-07-19): *"we should always reach for the robust best solution even if it takes longer to implement — we aim to solve once and never again instead of taking shortcuts so later it comes back to bite us."* And: *"never ever take shortcuts."*

If you catch yourself reaching for the quick path because the correct one is hard to get working, stop — that is precisely the moment this rule exists for. Do the harder, correct thing.

---

This rule applies to **everything you propose**, not just bug fixes. Refactors, features, UX changes, deploys, plan reviews, "let's start with the smallest slice" framing — all of it.

This is a recommendation-discipline rule, distinct from the in-code "never silence errors with try/except" rule (which lives in `CLAUDE.md` under *Debugging & Error Handling Philosophy*). That rule is about runtime behaviour; this one is about how you structure proposed work and present options.

## The rules

### 1. Never propose a bandaid as a stepping stone

Don't structure a plan as "Stage A: render whatever we already have; Stage B: actually do the right thing." If Stage A is something we'll throw away or rework once Stage B lands, it's a shortcut. Skip it. Recommend the root fix.

> ❌ "Stage A (~half day, frontend-only): render the events array we already receive in the WebSocket. Stage B (~1-2 days, backend): emit granular `Context.info()` log lines mid-tool."
>
> ✅ "Single coherent change: emit `Context.info()` log lines from inside long-running tools, then render them in the chat bubble. ~3 days end-to-end. The 'just render what we already have' shortcut is dropped — its output would be reworked once the granular emits land."

### 2. Never propose hiding a symptom while leaving the cause in place

If the API returns the wrong shape, fix the API. Don't pin a sidebar entry to mask a wrong `visible_sections` payload. Don't catch-and-rewrite an error message. Don't add a special-case branch in the consumer to paper over a producer that's miswiring data.

> ❌ "Add a 'Dashboard' nav item that's exempt from the `visible_sections` filter so the sidebar always has at least one entry."
>
> ✅ "The membership row for this user is `role=owner, persona=contributor`. The backend role policy upgrades that to admin sections. The frontend's `useActivePersona` ignores role and reads persona straight, so it picks contributor. Fix the persona resolution to mirror the backend rule."

### 3. "Cheapest signal" / "smallest visible improvement" is not a virtue

Henry has explicitly said he hates shortcuts. Cost arguments — "~half day vs. 1–2 days", "the cheapest signal that tells us X", "the smallest visible improvement" — do not justify recommending the shallow option first. Estimate honestly, recommend the deep fix, and let him pick if he wants the shallow one.

If you find yourself writing "the cheapest path to validate this", stop and re-frame. The cheapest path is rarely the right path; it's just the most pragmatic-sounding rationalisation for a shortcut.

### 4. If unsure whether something is shallow vs deep, ask

Don't pre-frame a plan as "let's start with A then do B" without flagging that A is throwaway. Either A *is* the root fix on its own (and B is genuine follow-on work that builds on it cleanly), or A is shortcut framing dressed up as pragmatism — name it and ask which one Henry wants.

A good test: "If I ship Phase A and we never get to Phase B, is the world meaningfully better, or is it the same as today?" If the answer is "the same as today, just with extra moving parts to maintain", Phase A is a shortcut.

### 5. Validate "already shipped" claims before recommending build-on work

Plan docs go stale. Code drifts from its README. Before proposing work that builds on an existing system ("let's just render the events stream we already have"), verify the system actually behaves as you think. Run a smoke test, read the call sites, query the live API. Don't extend a foundation you haven't checked.

This is doubly important after a long gap. The frontend `<DeepRunProgress />` *receives* the events array via the hook but *discards* it — a fact only visible by reading the component, not by trusting the comment that says "events array passed through to render". Same for backend service comments that lag behind code by weeks.

## Why this rule exists

Codified 2026-05-07 after a slip recommending a "Stage A: render the events array we already receive" cosmetic frontend slice as the cheapest path before suggesting the actual root fix (mid-tool `Context.info()` / `Context.report_progress()` emit on the backend, matching MCP-style log/progress notifications).

Henry's response, verbatim:

> *"I hate taking shortcuts — whenever you suggest these, make sure you only include deep fixes not bandaids. Put that in CLAUDE.md and AGENTS.md for next time."*

## Cross-references

- `CLAUDE.md` (backend) — *Debugging & Error Handling Philosophy* + *Recommendations & Proposed Work — No Shortcuts*
- `CLAUDE.md` (frontend, literacyseed) — extended *Never apply band-aid fixes* section
- `AGENTS.md` (frontend, literacyseed; backend AGENTS.md is gitignored) — *No Shortcuts in Recommendations*
- `~/.claude/projects/.../memory/feedback_no_shortcut_recommendations.md` — long-term memory entry
