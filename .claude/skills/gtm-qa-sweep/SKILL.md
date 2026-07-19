---
name: gtm-qa-sweep
description: Run the automated, persona-driven end-to-end QA sweep — drive a real browser (Playwright MCP) through each persona's GTM user journeys, assert expected-allow AND expected-deny, log issues, and (only in the unambiguous band) open a clean-worktree draft PR per fixable issue. Use when asked to "run the QA sweep / persona journeys / E2E matrix", after a significant change to a GTM surface, or as the body a scheduled cloud routine fires. Reads the `/personas` skill + `docs/qa/GTM_PERSONA_JOURNEY_MATRIX.md` for WHAT to drive. Pairs with `/octopus-ui-smoke` (single-surface smoke), `/pr` (PR mechanics), `/sred` (Linear tickets), and `.claude/rules/branching-strategy.md` (worktrees). NEVER auto-fixes money/webhook/auth-adjacent or any deny/amount/redirect assertion — those escalate with evidence.
---

# GTM Persona QA Sweep — The Harness

A scheduled (or on-demand) sweep that proves the GTM surface still works **for each persona**, end to end, in a real browser. Built to the practitioner patterns for persona-RBAC E2E + synthetic-journey monitoring: encode deny as a positive assertion, isolate test data, gate auto-fix on an unambiguous pass band, and quarantine flake so the signal stays trustworthy.

> **This sweep is the answer to "surprise issues that keep popping up."** It catches regressions across the whole persona × feature matrix on a cadence, instead of one surface at a time after something already broke.

> **Prefer the agent for full runs.** This skill is the **knowledge base + operational playbook**; the autonomous executor is the **`qa-agent` agent** (`.claude/agents/qa-agent.md`). Launch that agent (ideally `run_in_background: true`) for a real end-to-end pass — it starts from a clean context, reasons like a user, **provisions missing prerequisites** (switch to teamspace, create a recipient, create + attach a form, create an event), walks every GTM feature from each persona, and writes a full report (markdown + screenshots → PDF). It is on-demand / scheduled only — **never per-PR**. Use this skill's rules inline for quick, targeted checks; use the agent for the slow, thorough, whole-product sweep.

## What it reads (don't duplicate — reference)

- **`/personas`** — who each persona is, capability map, the deny set, the user stories.
- **`docs/qa/GTM_PERSONA_JOURNEY_MATRIX.md`** — the testable journeys (J1…J6 + cross-persona checks). This is the *what*; this skill is the *how*.
- **`.claude/rules/gtm-scope-freeze.md`** — what's in/out of GTM (never drive gated surfaces unless the flag is on for the QA workspace).

---

## 0. Target, accounts, isolation (HARD RULES)

**Scheduled/unattended sweep → demo CloudFront** (`https://d2wnv83yfoz6nw.cloudfront.net`, API `https://api.wanjala.art`). A cron can't keep localhost's docker + dev server alive. **On-demand after-change sweep → `http://localhost:3000`** is preferred when the stack is up (faster, no demo risk) — pick the target explicitly at the start of the run and record it.

**Accounts (never a real customer):**
- Demo, Stripe-test-ready, IS a workspace member: `c0d3henry@gmail.com` / `x1p-F00-b@r` → use for admin + sponsor money journeys on demo.
- Local seeded personas: `<persona>@test.octopi.dev` / `testpass123` (`seed_personas`). Local-only.
- **Never** a seed *sponsor* (e.g. `margaret.henderson@zaylan-demo.test`) for a per-user surface — they aren't members and bounce to onboarding.

**Operational notes (learned from the 2026-06-29 first run — don't relearn these):**
- **Local target CANNOT validate gated-feature deny.** Dev defaults all scope-freeze flags ON, so Marketplace/Grants/Bank/Forms/Contacts show in the admin sidebar locally. Run gated-deny assertions against **demo/prod** only.
- **Login is async (~2s).** After submitting credentials, **wait for the dashboard** (`browser_wait_for` ~2.5s or wait-for `/dashboard` URL) before asserting — an immediate snapshot still shows the login page.
- **Signout is a two-step: button → "Yes, log me out" confirm modal.** Clicking "Signout" only opens the modal; you must click the confirm button to actually log out (clicking once and navigating away is what produced the 2026-06-29 F1 false positive — logout never ran, tokens persisted). For fast persona-switching, skip the modal and just `browser_evaluate(() => { localStorage.clear(); sessionStorage.clear(); })` then navigate to `/identity/login`.
- **Screenshots must live under the repo** — Playwright MCP runs `--isolated` and only writes under `<repo>/.playwright-mcp/`. Use `.playwright-mcp/qa-sweep/<persona>-<journey>.png` (create the dir first); `~/Desktop/...` is denied.
- **Local backend is `http://api.local:8010`; frontend is `:3000`.** Confirm the login `POST` hits `api.local`, not the demo API.
- **Assert workspace CONTEXT before org flows.** Sponsorship / fundraising / recipients are **teamspace** surfaces. Confirm the active workspace is a **Teamspace** (e.g. Zaylan), not a personal/"Circle" workspace, before driving them — `c0d3henry` lands on a *personal* workspace by default, and `/sponsorship/<ws>` isn't workspace-type-gated, so you can wrongly create org data on a personal workspace (triage F5). Switch via the workspace switcher first.
- **Recipient creation is a 3-step wizard** (profile → location+auto-budget → needs+donation-form) that **persists incrementally** — a recipient can exist even if the final SUBMIT errors "required" (triage F4). Buttons are duplicated (hidden responsive copy) → click `nth(1)`/the visible one. After a create, verify the goal is set and tear it down (per-card Delete → confirm "Delete").
- **Donation forms per recipient are in scope.** Admins attach a donation form with custom **tiers / amounts / cover-fee** to a recipient; those drive the sponsor's checkout amounts. Drive: attach → tiers render on the public checkout → sponsor picks a tier → charge matches (`feature.donation_forms`). The builder is **Fundraising ▸ Forms ("NEW DONATION FORM")**. Open question to resolve: a workspace **Donation Form** may differ from a per-recipient **sponsorship plan** — confirm which the sponsor checkout consumes before relying on it.
- **When testing sponsorship, only select recipients that have NOT been sponsored before.** An already-sponsored recipient correctly shows no fresh SPONSOR button — that's expected, not a finding. (Sponsor amount/frequency state is per the recipient's plan.)
- **"No sponsorship plans yet … contact the organization to set up a plan" === the recipient has NO donation form / sponsorship plan configured.** Treat it as the F6 condition (un-sponsorable), not a transient state.
- **Provision your own test recipient if needed.** Seed data may have NO un-sponsored + plan-configured recipient (verified 2026-06-29). Be ready to create a recipient AND configure a plan/donation form before the charge — don't assume a sponsorable recipient exists.
- **A browser "CORS / No Access-Control-Allow-Origin" on the demo is usually a backend 5xx, not a CORS misconfig.** A 502 from nginx carries no CORS headers, so the browser blames CORS. **Curl the API directly** (`curl -s -o /dev/null -w '%{http_code}' https://api.wanjala.art/api/health/`) before chasing CORS config. The demo has brief login-outage windows during backend deploys — expected, but track it.
- **Capture per-step lag as a KPI** (Henry, 2026-06-29). Read `performance.getEntriesByType('navigation')[0].loadEventEnd` and key XHR durations per journey step; trend them per sweep. Functional-pass + lag-regression are both regressions.

**Deny assertion — what counts as a PASS (refined 2026-06-29):** a restricted route renders a **soft in-page "access-denied" panel at the same URL** ("your role doesn't include 'finance'"), NOT a 403/redirect. So assert: **(i)** the control is hidden in the persona's sidebar AND **(ii)** direct-navigating the restricted URL shows the access-denied panel **and NO protected data**. Don't require a redirect. A deny that *renders the protected data* is the leak you're hunting.

**Data isolation (so a write-journey never pollutes demo):**
1. **All writes scoped to a dedicated QA workspace** created at the top of the run (name it `QA Sweep <date>`), never an existing customer/demo-marketing workspace.
2. **Money steps use Stripe TEST cards only** (`4242…`). Confirm `STRIPE_MODE=test` before any checkout. Never a live card.
3. **Every write-journey owns a teardown** (matrix 🧹 steps) — archive/delete the QA workspace + children at the end. A failed run still attempts teardown.
4. **Tag synthetic data** in names (`[QA]` prefix) so anything that survives teardown is filterable/purgeable.

---

## 1. Per-run procedure

1. **Pick target + record metadata** (date, target env, frontend bundle hash if demo).
2. **Browser hygiene:** if `Browser is already in use … mcp-chrome-<id>`, `pkill -f "mcp-chrome-<id>"` then `rm -f <profile>/SingletonLock`.
3. **Per persona, in matrix order (J1…J6):**
   a. `browser_navigate` → target, `browser_snapshot` (read the a11y tree — drive off **real refs**, never hallucinated selectors → "live discovery").
   b. Log in as the persona's account. Prefer **role-based locators** (`getByRole`) over CSS — they survive markup churn.
   c. Walk each step. After each: `browser_console_messages` (a new console **red = regression**) and confirm the **allow** assertion.
   d. For **deny** assertions, do BOTH layers: (i) assert the control is **hidden** for that persona, AND (ii) **direct-navigate** to the restricted URL and assert it **bounces** (403/redirect), not serves. A deny that suddenly *allows* is the bug you're hunting — never heal it.
   e. Screenshot the success (or failure) state → `~/Desktop/claude-smoke/qa-sweep/<persona>-<journey>.png`.
4. **Cross-persona divergence checks** (CP1–CP3): same base path, three personas, assert each sees its correct variant.
5. **Teardown** all 🧹 state.
6. **Classify every failure** (§2), **act** (§3), **report** (§4).
7. `browser_close`.

---

## 2. Classify each failure (decides what happens next)

| Class | Definition | Action |
|---|---|---|
| **FLAKE** | Transient: network blip, timeout, one-off render race. Reruns green. | Rerun once. If green → note as flake, don't escalate. If it flakes repeatedly → **quarantine** (track, don't gate) and log. Target flake-rate < 2% per journey. |
| **HARNESS-COSMETIC** | The *test* is wrong in a provably product-orthogonal way: a `data-testid`/label WE own was renamed, a selector drifted, a route slug changed — and product behaviour is unchanged. | **Eligible for auto-draft-PR** (§3). |
| **PRODUCT BUG** | The app is actually broken: a step 500s, a surface won't load, data is wrong, a console red, a flow dead-ends. | **Escalate with evidence** — do NOT auto-fix. Triage doc + Linear SEE ticket. |
| **DENY/SEMANTIC** | A deny assertion flipped to allow; an amount/redirect/receipt/ledger value is wrong; anything money/webhook/auth-adjacent. | **Escalate, highest priority, NEVER auto-fix/heal.** This is a security/correctness signal. Human checkpoint per CLAUDE.md money carve-out. |

**Pass-rate gate for the run (the auto-fix governor):**
- **100% pass** → auto-draft-PRs for any HARNESS-COSMETIC fixes may proceed.
- **90–99% pass** → STOP auto-fixing. Escalate the failures to Henry with evidence; a partial failure is exactly when the agent must not decide whether the test or the app is wrong.
- **< 90% pass** → blocked. Something systemic (env down, auth broken, bundle stale). Report and stop; don't open PRs against a broken baseline.

---

## 3. Auto-fix flow (HARNESS-COSMETIC only, one clean worktree per issue)

Only for the HARNESS-COSMETIC class, only at 100% pass. Per issue:

```bash
git fetch origin
git worktree add .claude/worktrees/qa-<slug> -b fix/qa-<slug> origin/development
```
- Make the **minimal** fix (update the selector/locator/route the harness uses — or the product `data-testid` if WE own it and it's a no-behaviour-change rename). Read 2–3 existing tests first and copy their patterns.
- **Anti-bug-masking:** never make a check pass by gutting it — no `assert True`, no removed assertions, no placeholder. If the only way to "fix" it is to weaken an assertion, it's NOT cosmetic → reclassify as PRODUCT BUG and escalate.
- Open a **DRAFT PR** via `/pr` (base `development`), body = why + how + "Frontend impact" line + link to the run's triage doc. **Do not merge.** Henry reviews.
- Tear the worktree down when the PR merges: `git worktree remove .claude/worktrees/qa-<slug>`.

Everything else (PRODUCT BUG, DENY/SEMANTIC, the 90–99% band) → **no code**, escalate per §4.

---

## 4. Reporting

1. **Triage doc** at `docs/triage/QA_SWEEP_<YYYY-MM-DD>.md` in the established format (legend ✅✅/⚠️/❌/🔒/🧪; per-journey table; cross-cutting findings; sequenced TODO with S/M/L/XL effort). Include for each failure: persona, journey, step, class, screenshot path, console excerpt, network trace if relevant.
2. **Linear SEE tickets** for PRODUCT BUG + DENY/SEMANTIC issues — `seed` workspace, team UUID `d3aa3377-ff27-43ae-b0be-95bed2df4f56`, assignee `c0d3henry@gmail.com`, labels per `/sred` (repo:frontend/backend; sred:eligible vs sred:review). Carry repro steps. Link the draft PR if one exists.
3. **Append a run-summary block** to the matrix doc's "Run metadata" section (date, target, pass/quarantine/fail counts per journey, links).
4. **One-paragraph summary back to Henry**: target, pass-rate, what's green, what escalated (with ticket/PR links), what was auto-fixed (draft PRs awaiting his review).

---

## 5. Scheduling (cloud routine)

The sweep is the body a recurring cloud routine fires. Tiered cadence (synthetic-monitoring norm: critical paths often, everything else less):
- **Daily** full matrix sweep against demo (recommended default) — catches env + regression drift overnight.
- Optionally a lighter **money-path-only** sub-sweep (J2 sponsor donation) more frequently if demo stability is a concern.

Arm it with the `/schedule` skill (or `create_trigger`), firing a fresh session per run so each sweep starts clean:
- Prompt: "Run /gtm-qa-sweep against demo CloudFront. Follow the skill: isolate writes to a QA workspace, teardown after, classify failures, auto-draft-PR only HARNESS-COSMETIC at 100% pass, escalate everything else with evidence + Linear tickets."
- Cron (example): `0 6 * * *` (daily 06:00 UTC). Alert on **consecutive** failures, not a single blip.

Disable/adjust via `/schedule` (list → update/delete the trigger).

---

## 6. Extending coverage

- **New GTM surface or persona-specific section** → add a matrix row AND update `/personas` §2. The matrix coverage rule fails if a new `visible_sections` entry has no row — that's deliberate anti-staleness.
- **A gated feature graduates to GA** → move its journeys from the matrix "Out of scope" list into J1…Jn, in the same PR that flips the flag.
- **Seed the 3 missing personas** (`auditor`, `board_member`, `adviser`) → extend `seed_personas`, then add their journeys (mostly deny-set assertions mirroring sponsor/admin).

## 7. What this sweep must NEVER do
- Drive real customer accounts or live Stripe cards.
- Mutate an existing customer/demo-marketing workspace (writes go to the QA workspace only).
- Auto-fix/heal a deny, amount, redirect, receipt, ledger, or any money/webhook/auth assertion.
- Open a PR (even draft) when pass-rate < 100%, or merge any PR.
- Exercise gated/non-ICP surfaces unless the flag is explicitly on for the QA workspace.
- "Heal past" a real regression by weakening an assertion to make it green.

---

## 8. Regression traps the sweep MUST check (from real prod incidents)

Every one of these silently reached prod and was only caught by a hands-on E2E
(2026-07-12, the upload→generate wedge work). The sweep exists to catch their
recurrence — each is a cheap explicit check, not a new journey.

1. **Presigned uploads from the REAL app origin (S3 CORS drift).** The data
   bucket's CORS omitted `https://app.octopusintl.org`; every browser presigned
   PUT from the custom domain failed at preflight — File rows sat `pending`
   with NO error, no Celery task, nothing in Sentry-shaped logs. The sweep must
   include one presigned upload (a small PDF) driven from the CloudFront/app
   origin and assert the file's `processing_status` reaches `completed` (poll
   `GET /upload/<id>/`, ≤2 min). A row stuck `pending` with no error = the CORS
   / dispatch class — escalate, never skip.
2. **Async pipelines must be verified to their TERMINAL state.** A 200/201 on
   the dispatching endpoint proves nothing: the S3 `file.path` bug
   (`NotImplementedError` on S3MediaStorage) made every embed-on-upload fail
   AFTER a healthy-looking dispatch. Any journey that triggers background work
   (upload→index, report generate, newsletter generate) asserts the terminal
   state (status field / artifact exists), not the dispatch response.
3. **New endpoints get one live hit (stripped-provider-import class).** An
   F401 auto-fixer stripped a provider import; `from __future__ import
   annotations` hid it at import time; use-case unit tests inject fakes so no
   test ever called the provider factory — the endpoint 500'd a NameError only
   at request time. Composition-root smoke tests now call every
   `build_*` factory (see `test_shared_platform_provider.py` — replicate per
   context), and the sweep hits any endpoint added since the last run at least
   once, expecting non-5xx.
4. **Deploy really shipped (stale-container / masked-exit class).** A deploy
   chain piped `manage-ec2.sh deploy` into `tail`, masking a non-zero exit —
   the gate had refused (stale-worktree crash in the architecture suite) and
   prod silently kept old code through two "successful" deploy reports. After
   any backend deploy the sweep (or the deploy report) must verify: (a) the
   deploy's own success line, un-piped or with `pipefail`; (b) container
   uptime is YOUNGER than the deploy; (c) a marker from the shipped commit
   answers live (a new endpoint returning non-404, a schema field present).
   The 2026-06-28 variant ("No backend source changes detected" skipping
   restarts) is the same class — uptime check catches both.
