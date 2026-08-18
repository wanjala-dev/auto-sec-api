# auto-sec deep identity/admin QA (Playwright)

On-demand E2E smoke for the auto-sec HUD's identity + admin surfaces, revived
for the k8s stack (2026-08-08). Deeper and more mutation-heavy than the
committed frontend `e2e/` suite — run it when auth/admin surfaces change, not
on every push.

## How this fits vs the frontend `e2e/` suite

| Suite | Role | When |
|---|---|---|
| `auto-sec-frontend/e2e/` | Pre-demo backbone check: login, HUD core, scan, integrations, member RBAC — read-mostly against the seeded demo workspace | Before every demo / after HUD changes |
| `auto-sec-api/tests/qa/` (this) | Deeper identity/admin smoke: register, password reset with a real minted token, 2FA enrolment, sessions, profile edit, onboarding gate, members/permission matrix, kanban writes, DMs/feed — heavy on throwaway-fixture mutation | On demand, when identity/admin/collab surfaces change |

Both suites share one env contract (`E2E_*`), so a single shell drives either.

## Safety rules (enforced by the specs)

- The two demo logins (`test@autosec.local`, `member@autosec.local`) are used
  ONLY for read-only flows (login → sign out). Every spec that registers users
  or mutates auth state (2FA, password change, onboarding, membership writes)
  provisions its own throwaway `*@qa.autosec.local` fixture via the api pod —
  **no 2FA is ever enabled on the demo logins**, and registered throwaways are
  cleaned back out.
- Backend fixture glue runs through `kubectl -n autosec exec deploy/api` (see
  `helpers/backend.ts`) — the compose-era `docker exec` glue is gone.

## Prereqs

- The local k8s stack up (namespace `autosec`), `kubectl` on PATH.
- A frontend dev server (default the stable server on `:3015`). Never start
  your own server on 3010/3015 — those are Henry's.

## Run

```bash
cd tests/qa
npm install                      # first time
npx playwright install chromium  # first time
npx playwright test              # headless
npx playwright test --headed     # watch it
npx playwright show-report       # last HTML report
```

Env (all optional; mirrors `e2e/helpers/env.ts`):

| Var | Default |
|---|---|
| `E2E_BASE_URL` (legacy `QA_LOCAL_URL`) | `http://localhost:3015` |
| `E2E_EMAIL` (legacy `QA_ADMIN_EMAIL`) | `test@autosec.local` |
| `E2E_PASSWORD` (legacy `QA_ADMIN_PASSWORD`) | `AutoSecTest2026!` |
| `QA_KUBE_NS` | `autosec` |
| `QA_KUBE_TARGET` | `deploy/api` |
| `E2E_API_URL` (first-run only) | `http://autosec.local` |
| `E2E_GITHUB_PAT` (first-run only) | unset — GitHub connect legs skip loudly |
| `E2E_GITHUB_REPO` (first-run only) | unset — `owner/repo` on the PAT's allowlist |
| `E2E_SLACK_WEBHOOK` (first-run only) | unset — Slack verify leg skips loudly (posts a REAL message) |

## Suites

| Spec | Covers |
|---|---|
| `auth.smoke.spec.ts` | auth guard redirect · password masked-by-default · wrong-password rejected (throwaway user — lockout-safe) · login→HUD→sign-out (demo admin, read-only) · register (+terms gate, cleaned after) · forgot-password confirmation |
| `auth-recovery.smoke.spec.ts` | password reset-confirm with a REAL minted token · email confirmation token → verified |
| `twofactor.smoke.spec.ts` | 2FA enable via the real QR/verify flow (live TOTP computed in the api pod); torn down after |
| `sessions.smoke.spec.ts` | sessions list (THIS DEVICE) + sign out others |
| `profile.smoke.spec.ts` | profile edit + change password |
| `onboarding.smoke.spec.ts` | workspace-less operator gated to the guided Create→Teams→Start flow; single-workspace guard; gate never reappears |
| `kanban.smoke.spec.ts` | team board + seeded finding · Team↔Project board switch · add-column persists · add-task persists |
| `members.smoke.spec.ts` | roster + owner badge · role change · permission-matrix grant persists · invite operator |
| `collab.smoke.spec.ts` | DMs (deep-linked `?panel=messaging`) + operator feed (`?panel=social`, seeds its own workspace-scoped `feature.social_feed` rule) |
| `surfaces.smoke.spec.ts` | Reports studio draft save (no live LLM) · Workflows panel (inline builder) · dark⇄light toggle |
| `tenant-hosts.smoke.spec.ts` | Local multi-tenant parity (own Playwright project `tenant-hosts` — resolves `*.auto-sec.ai` in-browser, no /etc/hosts needed; prereq: the shared tenant HUD dev server on :3050): every tenant host serves the HUD at root, branded from the registry (heading == that host's own `/tenant/login-brand/`) · API calls same-origin (Host binds the tenant) · a tenant login only works on its own host (cross-host + pooled-creds negatives) · JWT websocket handshake on the tenant host (/ws → channels) · pooled console untouched. Run: `npx playwright test --project tenant-hosts` |
| `first-run.spec.ts` | The from-zero customer journey: UI register → verification gate (minted token) → guided workspace create → default-desk sanity + SETUP 0/5 funnel → invite a viewer → token accept → viewer deny → setup chip ticks 1/5 → GitHub connect + repo scan → finding/triage-chip/snippet/draft-PR affordance (needs `E2E_GITHUB_PAT`/`E2E_GITHUB_REPO`, else skips loudly) → Slack fail-loud validation + real webhook verify (needs `E2E_SLACK_WEBHOOK`) → AWS wizard to the role handoff + fail-loud verify · torn down after |

## Adding specs

Widen the `autosec` project's `testMatch` in `playwright.config.ts`. Keep specs
self-contained and idempotent: throwaway `*@qa.autosec.local` fixtures via
`helpers/backend.ts`, unique timestamped names for created rows, and never
mutate the demo logins' auth state.

> This harness keeps earning its keep: the 2026-08-08 revival run caught a live
> backend regression — team-board add-column rejected by the conditional
> unique validator (`project: This field is required.`) — root-fixed in its own
> PR. (Earlier catches: register rejecting `+`/`.`/`-` emails; reset flow
> redirecting to a dead route.)
