# auto-sec End-to-End QA (Playwright)

Localhost E2E smoke for the auto-sec HUD, ported from the Wanjala qa harness and
retuned for this product. Grows one spec at a time as features land.

## Prereqs
- auto-sec stack up (`auto_sec-web-1` on :8020) — a verified admin
  (`admin@octopus.local`) exists from boot.
- Frontend dev server on **:3001** (`npm start` in `auto-sec-frontend`).

## Run
```bash
cd tests/qa
npm install                      # first time
npx playwright install chromium  # first time
npx playwright test              # headless
npx playwright test --headed     # watch it
npx playwright show-report       # last HTML report
```
Override creds with `QA_ADMIN_EMAIL` / `QA_ADMIN_PASSWORD`; base URL with
`QA_LOCAL_URL`.

## Suites
| Spec | Covers |
|---|---|
| `auth.smoke.spec.ts` | auth guard redirect · password masked-by-default · wrong-password rejected · login→HUD→sign-out · register (+terms gate) · forgot-password confirmation |
| `kanban.smoke.spec.ts` | team board renders columns + seeded finding · Team↔Project board switch · add-column persists · add-task persists (teams / projects / columns / tasks / board switcher) |
| `members.smoke.spec.ts` | roster + owner badge · role change (admin→root) · permission-matrix direct grant persists · invite operator (Settings ▸ Workspace ▸ Members) |

## Adding specs
Point new `testMatch` entries in `playwright.config.ts`, or widen the existing
`autosec` project's match. Keep specs self-contained and idempotent (unique
`qa+<timestamp>@octopus.local` emails for register). This suite is the repeatable
smoke net — extend it as onboarding, 2FA, sessions, profile, and org-audit land.

> This harness has already earned its keep: its first run caught two real bugs
> manual testing missed — register rejecting emails with `+`/`.`/`-` (non-
> alphanumeric derived username) and the reset flow redirecting to a
> non-existent `/identity/reset-confirm/` page. Both fixed.
