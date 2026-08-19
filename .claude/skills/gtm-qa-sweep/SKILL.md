---
name: gtm-qa-sweep
description: Run the persona-driven end-to-end QA sweep against Auto-Sec (autosec) — drive the HUD and the API through the real security loops (AWS connect → audit role → verify → Prowler CSPM; Trivy container scan; Opengrep code scan → draft PR; log sources; delivery/Slack; findings → triage → board; RBAC; billing; tenant isolation), assert expected-allow AND expected-deny, probe the defect classes that have actually bitten us, and report honestly. Use when asked to "run the QA sweep / persona journeys / E2E matrix", after a significant change to a core loop, or as the body a scheduled routine fires. Carries the RULES OF ENGAGEMENT that every QA agent must obey against shared state — read §0 before touching anything. References `/personas`, `/tenancy`, `tests/qa/README.md`, and `.claude/rules/*` rather than duplicating them. NEVER auto-fixes auth/money/tenant-isolation or any deny assertion — those escalate with evidence.
---

# Auto-Sec QA Sweep — The Harness

A sweep that proves autosec's **core security loops** still work end to end, for each persona, against
the live local stack. Built to the practitioner patterns for persona-RBAC E2E and synthetic-journey
monitoring: encode deny as a positive assertion, drive off live discovery, isolate test data, gate
auto-fix on an unambiguous pass band, quarantine flake.

> **This skill is autosec-local (Tier 2) and stays local.** Shared engineering-craft skills come from
> the `wanjala-core@wanjala-kit` plugin and must **never** be copied in here — see
> `.claude/rules/skills-and-plugins.md`. If you ever find yourself grepping the filesystem for a
> SKILL.md, stop: the plugin isn't loaded and what you found is unowned.

## What it reads (reference — do not duplicate)

| Source | What it gives you |
|---|---|
| `/personas` skill | Who each persona is, persona-vs-role, the deny set. **Note:** it still carries fork-drift (donor/sponsor language) — trust its persona-vs-role *model*, verify its examples. |
| `/tenancy` skill | The pooled-vs-dedicated model and the traps that have already bitten this codebase. Read before any cross-tenant assertion. |
| `/architecture` skill | Layer rules — needed to judge whether a defect is a boundary violation. |
| `tests/qa/README.md` + `tests/qa/*.spec.ts` | **The existing runnable harness.** Playwright suite covering auth, 2FA, sessions, profile, onboarding, kanban, members, collab, surfaces, tenant-hosts, and `first-run.spec.ts` (the from-zero customer journey). Extend this before writing anything new. |
| `.claude/rules/branching-strategy.md` | Worktree + PR mechanics for any fix. |
| `.claude/rules/no-shortcuts.md`, `verify-dont-guess.md` | Why you never heal a failing assertion. |

There is **no `docs/qa/` directory** in this repo — `tests/qa/` is the harness and its README is the
matrix. Don't cite a path you haven't checked.

---

# §0. RULES OF ENGAGEMENT — what a QA agent must NEVER do

**Read this before any other section. Seven agents in the 96-agent sweep were flagged for unsafe
actions against shared state. This must never recur.**

The stack under test is **shared**: one database, one Redis broker, one browser, live tenants Henry
actually uses, and other agents working concurrently. A QA agent has no mandate to damage it. Finding
a real bug never justifies causing one.

### 0.1 Never print credentials — not even truncated

One agent echoed portions of the live **GitHub App private key** and the **webhook signing secret**
into its transcript, read out of Django settings and out of a base64-decoded k8s Secret. It reasoned
that showing a length and the first 30 characters was safe. **It is not.** Those credentials now need
rotating.

- Never `print`/echo a settings value, env var, or Secret whose name contains `KEY`, `SECRET`,
  `TOKEN`, `PASSWORD`, `CREDENTIAL`, `PRIVATE`, or `SIGNING`.
- Never `kubectl get secret -o yaml` / `-o jsonpath` and decode it into your transcript.
- To prove a credential is *present*, assert a boolean: `bool(settings.X)` → `True`. Never its value,
  prefix, suffix, or length.
- Test passwords documented in this skill are the sole exception — they are seeded fixtures, not
  secrets.

### 0.2 Never mutate the shared Celery broker

One agent ran `redis-cli ltrim celery 4 -1`, destroying queue entries **by index**, without
establishing that those entries were its own. That can silently drop other workers' tasks and
beat-scheduled work belonging to the whole stack.

- Redis is **read-only** for QA. `LLEN`, `LRANGE`, `KEYS`, `GET` are fine. `LTRIM`, `DEL`, `FLUSHDB`,
  `RPOP`, `XTRIM` are forbidden.
- To observe your own task, correlate on **your** task id from the dispatch response — don't reshape
  the queue to make it observable.

### 0.3 Never forge webhook signatures, never delete-then-guess-a-restore

One agent forged Stripe webhook signatures with the live signing secret and deleted `Workspace`,
`Team`, `PaymentEvent`, and `PaymentTransaction` rows from the shared demo database, then
*approximated* a restore from memory.

- **There is no undo for a guessed restore.** Reconstructed rows are not the original rows; they are
  fabricated data wearing the original's ids.
- Never forge a signature with a real secret. Test signature *rejection* (a bad signature must 400) —
  that's the security assertion that matters, and it needs no valid secret.
- Money/webhook paths are escalate-only. See §5.

### 0.4 Never run destructive probes against a live tenant

One agent ran unauthenticated `DELETE`s against user records on **`wanjala.auto-sec.ai`** — a real,
registered, dedicated tenant Henry was actively using, not a documented test tenant.

- A tenant existing in the registry is **not** permission to mutate it. `faura`, `wanjala`, `acme`,
  and `senso` are all real registered tenants (§1.3).
- Destructive probes run **only** against throwaway accounts the agent created itself, in a workspace
  it created itself.
- "I needed to prove the endpoint was exploitable" is answered by proving it on your own throwaway
  row. The vulnerability is identical; the blast radius is not.

### 0.5 Never mutate real rows via `kubectl exec … manage.py shell`

One agent flipped a real workspace's `privacy` field through the Django shell to set up a test.

- The shell is for **read-only** verification: counts, existence checks, reading a field you just
  wrote through the API.
- Set up state **through the product's own API** — that's also what you're supposed to be testing. A
  shell-configured fixture proves the shell works, not the product.
- `.save()`, `.delete()`, `.update()`, `.create()` on pre-existing rows: forbidden. Provisioning
  throwaway fixtures via `tests/qa/helpers/backend.ts` is the sanctioned path.

### 0.6 Delete only what you provably created this session

Two agents deleted `DeepRun` and conversation rows they had found by **query or pattern-match**
rather than by their own creation.

- **"Found by a list query" is not provenance.** Neither is a matching name prefix, nor a recent
  timestamp — another agent was running concurrently.
- Hold the ids you created, in memory, from the create response. Delete exactly those. If you lost
  the id, you have lost the right to delete the row.

### 0.7 The browser is shared — attribute before you report

One agent had its tab navigated out from under it **three times** mid-journey by another session, and
came close to reporting another agent's navigation as a product defect.

- Never clobber another session's tab. Prefer your own context/tab; if state changes without your
  action, treat it as contamination, not a finding.
- Before reporting "the app navigated away by itself", re-run the step in a clean context. An
  unreproducible navigation is a FLAKE at best.

### 0.8 Never forge or mint a JWT

Obtain tokens from the product's own endpoints (`POST /identity/login/`, the OTP verify step, the
magic-link verify). Hand-minting a token to skip login invalidates every authorization assertion
downstream — you'd be testing your forgery, not the product. This is a standing repo rule, not a
QA-only one.

### 0.9 Read-only by default

If a journey can be asserted without a write, assert it without a write. Writes are a deliberate,
justified, torn-down exception — not the default posture.

---

# §1. Targets, accounts, isolation

## 1.1 Targets (verified live)

| Surface | How to reach it | Verified |
|---|---|---|
| **API (ingress)** | `http://autosec.local` — add `127.0.0.1 autosec.local` to `/etc/hosts` | `GET /api/health/` → `200 {"status":"ok"}` |
| **API (port-forward)** | `kubectl -n autosec port-forward svc/api 8000:8000` | fallback when ingress is unhappy |
| **HUD frontend** | dev server on **`:3050`**, served from the worktree `worktrees/tenant-hud-dev` | `http://localhost:3050/` → 200 |
| **Tenant hosts** | same dev server / gateway, bound by **Host header**: `faura.auto-sec.ai:3050`, `wanjala.auto-sec.ai:3050`, `senso…`, `acme…` | brand endpoint resolves per host (§1.3) |

**`:3010` is the Excalidraw MCP server, NOT the HUD.** Verified by process:
`mcp-excalidraw-server/dist/server.js`. Never drive QA against it, and never restart it.

**Never start your own dev server on `:3010` or `:3050`, and never kill one.** They are Henry's. To
confirm which worktree is serving `:3050`:

```bash
lsof -nP -iTCP:3050 -sTCP:LISTEN          # -> pid
lsof -p <pid> -a -d cwd -Fn               # -> the worktree path
```

> **Stale default to override:** `tests/qa/playwright.config.ts` defaults `E2E_BASE_URL` to
> `http://localhost:3015`, and nothing is listening there. Pass `E2E_BASE_URL=http://localhost:3050`
> explicitly, and record the target you actually used in the report.

## 1.2 Accounts

| Account | Password | Use |
|---|---|---|
| `test@autosec.local` | `AutoSecTest2026!` | Seeded demo admin, workspace `cc287133-b53c-43c8-9000-2873f8c8a1e3`. **Read-mostly.** |
| `member@autosec.local` | as seeded | Second seeded login for member/RBAC divergence checks. Read-mostly. |
| `admin@acme.test` | as seeded | The `acme` dedicated tenant's admin — reachable only on the acme host/DB. |
| `*@qa.autosec.local` | self-set | **Throwaway fixtures you provision yourself.** All mutation-heavy work goes here. |

`test@autosec.local` and `member@autosec.local` verified present in the pooled database. **Never
enable 2FA on a demo login** and never change its password — `tests/qa/` depends on their auth state
being pristine.

## 1.3 Tenants (verified live from the registry)

| Subdomain | Name | Isolation | Database |
|---|---|---|---|
| `senso` | Senso | **pooled** | `default` (workspace `cc287133-…` — the demo workspace) |
| `acme` | Acme Corp | **dedicated** | `tenant_acme` |
| `faura` | Faura | **dedicated** | `tenant_faura` |
| `wanjala` | Wanjala | **dedicated** | `tenant_wanjala` |

Brand resolution is by **Host header**, verified:

```bash
curl -s -H 'Host: faura.auto-sec.ai' http://127.0.0.1/api/v1/tenant/login-brand/
# {"name":"Faura","subdomain":"faura","branded":true}
curl -s -H 'Host: unknown-xyz.auto-sec.ai' http://127.0.0.1/api/v1/tenant/login-brand/
# "Organization not found."  [404 — rejected at the middleware, before the view]
```

**All four are real tenants. None is a scratch pad.** See §0.4.

## 1.4 Tenant isolation is the assertion that matters most

autosec runs **two tiers** (`/tenancy`), and the QA consequence differs per tier:

- **Pooled tier** — shared database, isolation enforced **in application code** by filtering on
  `workspace_id`. A missing filter **is** the tenant boundary; there is no database behind it to
  catch you. Every read/write seam needs an explicit **cross-tenant deny assertion**.
- **Dedicated tier** — separate database per tenant (`tenant_acme`, `tenant_faura`,
  `tenant_wanjala`), selected by the router.

Two verified facts that will trip you up:

1. `DATABASE_ROUTERS` is **`['components.shared_platform.infrastructure.tenancy.router.TenantRouter']`**
   and `DATABASES` has aliases `default`, `tenant_acme`, `tenant_faura`, `tenant_wanjala`.
   *(`CLAUDE.md` and `.claude/rules/django-conventions.md` still describe autosec as single-DB with
   `DATABASE_ROUTERS = []`. That is now stale — verify against settings, per `verify-dont-guess.md`.)*
2. Any ORM access with no tenant bound raises **`UnboundTenantError`**. In a read-only shell you must
   bind explicitly:
   ```python
   from components.shared_platform.infrastructure.tenancy.context import pooled_context
   with pooled_context():
       ...   # read-only queries only (§0.5)
   ```
   This is a feature: a silent fallback to `default` would be a cross-tenant read.

## 1.5 Data isolation for write journeys

1. Writes go to a **workspace the sweep created itself**, named `[QA] Sweep <date>` — never an
   existing workspace, never a live tenant.
2. Throwaway users are `*@qa.autosec.local`, provisioned via `tests/qa/helpers/backend.ts`.
3. Every write journey owns a **teardown**, and a failed run still attempts it.
4. Tag synthetic data with a `[QA]` prefix so survivors are filterable.
5. Money steps: **test mode only**, and see §0.3 — the webhook path is escalate-only.

---

# §2. The journeys — autosec's real core loops

Paths below are **root-mounted** (there is no `/api/` prefix on product routes); `/api/v0/…` and
`/api/v1/…` are equivalent versioned aliases. `/api/health/` is root-only and unversioned.

| # | Journey | Key path(s) |
|---|---|---|
| **J1** | **AWS connect → audit role → verify → CSPM** | `POST /integrations/workspaces/<ws>/aws/` → `GET …/aws/<conn>/cloudformation/` (`?fmt=terraform` for TF; carries `launch_url`) → `POST …/aws/<conn>/verify/` → `POST …/aws/<conn>/scan/` (202) → `GET /cloud-posture/workspaces/<ws>/summary/` + `/findings/` |
| **J2** | **Container scan (Trivy)** | `POST /container-security/workspaces/<ws>/scan/` (202; image in the body) → `GET …/scans/<run>/sbom/` |
| **J3** | **Code scan (SAST/Opengrep) → draft PR** | `GET /code-security/workspaces/<ws>/repos/` → `POST …/scan/` (202) → `GET …/snapshots/?repo=owner/repo` → `POST /integrations/workspaces/<ws>/findings/<task_id>/preview-draft-pr/` → `…/open-draft-pr/` |
| **J4** | **Log sources → ingest** | `POST /integrations/workspaces/<ws>/log-sources/` (`kind` ∈ `s3`, `cloudwatch`) → `POST …/<source>/verify/` |
| **J5** | **Delivery / Slack fanout** | `POST /integrations/workspaces/<ws>/delivery-connections/` (`kind: slack`) → `…/<conn>/verify/` — **posts a REAL message**; use your own webhook |
| **J6** | **Findings → triage → board** | `GET /findings/workspaces/<ws>/` → `…/<finding>/status/` (`resolve`/`suppress`/`reopen`) → follow `triage.task_id` into `/project/tasks/<id>/` |
| **J7** | **Identity / auth** | `/identity/login/`, `/identity/register/`, `/identity/me/sessions/`, `…/revoke-others/`, `/identity/changepassword/`, `/identity/request-reset-email/`, `/identity/otp/*`, `/identity/magic-link/*`, `/identity/users/` |
| **J8** | **Org / team / membership RBAC** | `/workspaces/`, `/workspaces/<ws>/members/effective-permissions/`, `…/members/<user>/role/`, `…/permissions/`, `/membership/invitations/`, `/team/` |
| **J9** | **Billing / subscription tiers** | `/workspaces/billing/overview/`, `/plans/`, `/plan/preview/`, `/plan/change/` — workspace comes from the **body/query**, not the path |
| **J10** | **Tenant isolation** | Per §1.3/§1.4: a tenant's login works only on its own host; cross-host and pooled-credential attempts must be denied |

Supporting surfaces a sweep will touch: `/jobs/workspaces/<ws>/active/` (async scan progress),
`/feature-flags/`, `/cloud-graph/workspaces/<ws>/attack-paths/`, `/response/workspaces/<ws>/actions/*`,
`/sign-off/pending/`, `/audit/entries/`, `/ai/agents/runs/`.

**Async loops must be verified to their TERMINAL state.** A 202 on a scan dispatch proves nothing —
poll `/jobs/workspaces/<ws>/<job_id>/` (or the scan's own status) until terminal. Several defects
below are *only* visible past the dispatch response.

**Known non-obvious behaviours** (verified in the routing, don't re-derive):
- `verify` on an AWS connection is **not passive** — it calls `verify_and_scan(...)` and returns a
  `scans` summary. Don't assert "verify, then manually scan".
- Scan-now returns **409** with `skipped_reason` when the pillar is off, **429** + `Retry-After` when
  gated/deferred, **202** on success. All three are correct outcomes, not failures.
- Draft-PR routes take `<str:task_id>` deliberately: a malformed id must return the typed
  `finding_not_found` JSON error, not a bare URL 404.
- `/identity/password-reset-complete` has **no trailing slash**.

---

# §3. Defect classes to actively probe

The 96-agent sweep surfaced **21 real defects**. The *patterns* are worth more than the instances —
probe each one deliberately.

### 3.1 Per-verb authorization on viewsets
A permission class whose **every branch returns `True`**, and which defines **no
`has_object_permission`**, passes by default in DRF. Found on `destroy` in the identity `UserViewSet`:
`GET /identity/users/<id>/` correctly 401'd while **`DELETE` on the same viewset returned 204 and hard-deleted
the row, cross-tenant**.

> **Probe every verb on a viewset independently. Never infer DELETE's authz from GET's.**
> For each viewset: GET list, GET detail, POST, PATCH, PUT, DELETE — unauthenticated, then
> authenticated-as-another-tenant. Six assertions, not one.

### 3.2 Unauthenticated list / enumeration
`GET /workspaces/` and `GET /identity/users/` leaked cross-tenant rows and owner email addresses with
no credentials at all.

> Hit **every list endpoint with no `Authorization` header**. Expect 401/403. A 200 with rows is a
> breach, not a finding to batch for later.

### 3.3 Two-step auth where the intermediate token is full-privilege
The login `preauth_token` — the interstitial issued when TOTP is enabled — was **accepted by every
authenticated endpoint**: a complete 2FA bypass. A second, independent bypass existed via magic link.

> Any multi-step auth mint gets this probe: take the **intermediate** artifact and replay it against a
> protected read, a protected write, and the WebSocket handshake. All three must reject. Then probe
> *every other* path that mints a session (magic link, OAuth, invite accept) — bypasses come in pairs.

### 3.4 Session lifecycle lies
Password reset and password change **did not revoke existing sessions**. "Revoke session" and "log
out" both reported success while the access token kept working.

> Never trust the success response. After any revoke/logout/password-change, **replay the old token**
> against a protected endpoint. Success = defect.

### 3.5 Policy enforced at one entry point only
The password policy was enforced on change-password but **not** on register or reset.

> For every policy (password strength, email validation, quota, role gate), enumerate **all** entry
> points that write the same field and assert the policy at each.

### 3.6 Swallowed exceptions killing a subsystem silently
Three separate instances: a caught RAG error killed **100% of async deep runs**; a missing pgvector
embedding column made **every** vector search raise; an import of a non-existent class killed **every**
critical/high finding before notify.

> A `try/except` that logs and continues turns a total outage into a quiet one. Probe by asserting the
> **terminal state and the artifact**, never the dispatch. If a subsystem's success rate is 0%, no
> endpoint will tell you — check the output actually exists.

### 3.7 NULL / absent resolving to the most permissive outcome
A **NULL plan resolved to UNLIMITED entitlements**.

> For every gate, test the **absent** case explicitly: no plan, no membership row, no persona, no
> flag. Absent must fail closed. This is the single highest-yield probe in the list.

### 3.8 Provenance falsehoods
An auto-opened draft PR claimed **an operator had approved the patch**. Nobody had.

> Read the artifacts the product generates — PR bodies, board comments, audit entries, notification
> text — and assert every factual claim is true. A false provenance claim is a correctness defect of
> the highest severity: the product's whole value is that its claims can be trusted.

### 3.9 Cross-tenant filtering (pooled tier)
Per §1.4 — a missing `workspace_id` filter is the boundary.

> Every read/write seam gets an explicit cross-tenant deny assertion: authenticate as tenant A, request
> tenant B's resource id, assert 403/404 **and no data in the body**.

---

# §4. Per-run procedure

1. **Read §0.** Record target, date, and which dev server/worktree is serving `:3050`.
2. **Confirm the stack:** `kubectl -n autosec get pods` all Running; `curl http://autosec.local/api/health/`
   → `{"status":"ok"}`.
3. **Prefer the existing harness.** `cd tests/qa && E2E_BASE_URL=http://localhost:3050 npx playwright test`
   before hand-driving anything. Extend a spec rather than inventing a parallel one.
4. **Per journey (§2), per persona:** drive off **live discovery** — `browser_snapshot`, read the a11y
   tree, use **role-based locators** (`getByRole`), never hallucinated CSS selectors.
5. **Login is async.** Wait for the HUD (URL change or a known landmark) before asserting; an immediate
   snapshot still shows the login form.
6. After each step: check console for new reds, assert the **allow** outcome, and capture **per-step
   lag** as a KPI (`performance.getEntriesByType('navigation')[0].loadEventEnd` + key XHR durations).
   Functional-pass with a lag regression is still a regression.
7. **Deny assertions get both layers:** (i) the control is hidden for that persona, **and**
   (ii) direct-navigating / direct-calling the restricted resource denies **and returns no protected
   data**. A soft in-page "access denied" panel at the same URL is a PASS — don't require a redirect.
   A deny that renders the protected data is the leak you're hunting.
8. **Run the §3 probe checklist** against anything new since the last sweep.
9. **Teardown** everything you created (§0.6 — only what you created).
10. Classify (§5), report (§7).

**Artifacts never land in the repo.** Screenshots, snapshots, traces → the MCP `--output-dir`
(`~/Desktop/claude-smoke`) or the session scratchpad, by **absolute** path. `tests/qa/test-results/`
is gitignored and fine. See `.claude/rules/repo-hygiene.md` §4 — a bare filename resolves against the
CWD, which is a worktree, and that's how 59 stray artifacts once accumulated at the repo root.

**A browser "CORS / No Access-Control-Allow-Origin" error is usually a backend 5xx, not a CORS
misconfig.** A 502 carries no CORS headers, so the browser blames CORS. `curl` the API directly before
chasing CORS config.

---

# §5. Classify each failure

| Class | Definition | Action |
|---|---|---|
| **FLAKE** | Transient: network blip, timeout, render race, **or another agent's navigation** (§0.7). Reruns green. | Rerun once. Repeated → quarantine (track, don't gate). Target < 2% per journey. |
| **HARNESS-COSMETIC** | The *test* is wrong in a provably product-orthogonal way — a locator/testid/route slug we own drifted, product behaviour unchanged. | Eligible for auto-draft-PR (§6). |
| **PRODUCT BUG** | The app is broken: a step 500s, a surface won't load, data is wrong, an async loop never reaches terminal state. | **Escalate with evidence.** No auto-fix. |
| **SECURITY / SEMANTIC** | Any §3 class: authz bypass, unauthenticated enumeration, 2FA bypass, session lifecycle lie, cross-tenant leak, permissive NULL, provenance falsehood. Anything money/webhook/auth-adjacent. | **Escalate, highest priority, NEVER auto-fix.** Human checkpoint. |

**Pass-rate gate (the auto-fix governor):**
- **100%** → HARNESS-COSMETIC draft PRs may proceed.
- **90–99%** → stop auto-fixing; escalate with evidence. A partial failure is exactly when an agent
  must not decide whether the test or the app is wrong.
- **< 90%** → blocked. Something systemic. Report and stop.

---

# §6. Honest-reporting practices (these worked — keep them)

1. **Reproduce the defect live before fixing it.** A defect you inferred from reading code, but never
   triggered, is a hypothesis.
2. **Write the test and watch it FAIL first.** A test that never failed proves nothing about the fix.
3. **Check whether the failure also fails on untouched `main` before attributing it.** This sweep
   correctly identified **6 pre-existing identity failures** that way — and did not blame them on the
   change under test.
4. **Report the blast radius honestly**, including your own mistakes. An agent that quietly restores
   what it broke has produced a corrupted database *and* a false report.
5. **Never weaken an assertion to make it green.** If the only way to "fix" it is to remove the check,
   it's a PRODUCT BUG — reclassify and escalate (`.claude/rules/no-shortcuts.md`).

---

# §7. Auto-fix flow (HARNESS-COSMETIC only, 100% pass only)

One **fresh external worktree per issue**, never a primary clone (`.claude/rules/branching-strategy.md`):

```bash
git -C /Users/henrywanjala/Desktop/auto-sec/auto-sec-api fetch origin
git -C /Users/henrywanjala/Desktop/auto-sec/auto-sec-api worktree add \
  /Users/henrywanjala/Desktop/auto-sec/worktrees/qa-<slug> -b fix/qa-<slug> origin/main
```

- Make the **minimal** fix. Read 2–3 existing specs first and copy their patterns.
- Open a **draft PR** (`gh pr create --base main`). **Never merge** — merges happen only on Henry's
  word. No `Co-Authored-By: Claude`, ever.
- Kill any dev server rooted in the worktree **before** `git worktree remove`.

Everything else → no code, escalate per §8.

---

# §8. Reporting

1. **Run report** (scratchpad or `docs/reviews/`, per `.claude/rules/repo-hygiene.md` §1 — never the
   repo root): target, date, pass-rate, per-journey table, and for each failure the persona, journey,
   step, class, evidence path, console excerpt, and network trace.
2. **Every §3-class finding gets a reproduction** — exact request, exact response, exact identities.
3. **Declare any state you touched**, including anything you created and failed to tear down.
4. **One-paragraph summary**: target, pass-rate, what's green, what escalated, what's awaiting review.

---

# §9. Extending coverage

- New core loop or pillar → add a **§2 journey row** and a spec in `tests/qa/`, in the same PR.
- New endpoint → it gets at least one live hit (expect non-5xx) plus the §3.1 per-verb matrix and the
  §3.2 unauthenticated probe **before** it's considered covered.
- New auth mint path → §3.3 replay probe is mandatory.
- A flag graduates to GA → move its journeys out of the gated list in the same PR that flips the flag.

> **`.claude/agents/qa-agent.md` is fork-drifted** — it still drives sponsors, recipients, donations,
> Zaylan teamspaces, and `api.wanjala.art`, none of which exist in autosec. Do **not** launch it as an
> autonomous executor against this skill until it is rewritten. Use `tests/qa/` plus this skill's
> procedure instead.
