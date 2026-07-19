---
name: personas
description: Source of truth for the platform's PERSONAS — who each persona is, the persona-vs-role model, what each persona can SEE and DO vs is correctly DENIED, and the "as a persona X I want to…" user stories / day-in-the-life journeys per persona. Use BEFORE designing any persona-specific surface, writing persona E2E journeys, reasoning about visible_sections/sidebar gating, or deciding whether a permission outcome is a bug or correct RBAC. Pairs with `/gtm-qa-sweep` (the runnable harness that drives these journeys), `/navigation` (sidebar IA), `/sponsor-persona` (deep dive on the donor), and `/architecture` (layer rules). Grounded in `components/identity/domain/policies/workspace_role_policy.py` + ADR 0002, NOT the stale memory file.
---

# Personas — The Single Source of Truth

This skill is the canonical reference for the platform's personas. It answers three questions:

1. **Who is each persona** and how do they differ from RBAC roles?
2. **What can each persona SEE and DO** — and, just as importantly, what are they *correctly* denied (so a working permission gate is never mistaken for a bug)?
3. **What does a day in their life look like** — the "as a persona X, I want to…" user stories that the `/gtm-qa-sweep` harness drives end to end.

Canonical code sources (read these, not the 85-day-old `project_personas_dashboard.md` memory file, which is stale at 4 personas):

- **Persona enum** — `infrastructure/persistence/workspaces/models.py` (`class Persona(models.TextChoices)`)
- **Role → visible_sections policy** — `components/identity/domain/policies/workspace_role_policy.py` (`resolve_workspace_role()`)
- **Design rationale** — `docs/adr/0002-personas-and-rbac.md`
- **Invitable personas + default roles** — `components/team/application/use_cases/create_workspace_invite_use_case.py`
- **Seed accounts** — `components/identity/cli/management/commands/seed_personas.py`
- **Exposed to frontend** — `GET /identity/me/summary/` emits `role` + `persona` + `visible_sections` per workspace.

---

## 1. Persona ≠ Role (the load-bearing distinction)

Two orthogonal axes live on `WorkspaceMembership`:

| Axis | Field | What it controls | Who reads it |
|---|---|---|---|
| **RBAC** | `role` (`owner` / `admin` / `member` / `viewer`) | **Permission gate.** Every authorization decision. | Backend permission checks + `@requires_role` ONLY. Never UI logic. |
| **Experience** | `persona` (9 values below) | **UX lens.** Which dashboard, sidebar sections, copy. | Frontend dashboard dispatch + sidebar filtering. Never a permission check. |

**The invariant (ADR 0002 §1):** a check like `if persona == 'sponsor': forbid_x` is a bug. Forbidding happens on `role`. A user can be `admin` in workspace A and `sponsor` in workspace B — both stored independently per membership row.

**Why this matters for QA:** a sponsor (role `viewer`) being **blocked** from a write is *correct behaviour*, not a defect. The journey matrix must encode **expected-allow** vs **expected-deny** per persona. A deny is asserted as a positive outcome (control hidden AND restricted URL bounces to 403/redirect) — see `/gtm-qa-sweep`.

---

## 2. The 9 personas

| Persona | Default role | `visible_sections` | Posture | Seeded? | Invitable? |
|---|---|---|---|---|---|
| **admin** | admin | ai, fundraising, teams, workflows, finance, projects, settings, sponsorship, campaigns, donations, grants | RW — runs the org | ✅ `admin@test.octopi.dev` | ✅ |
| **contributor** | member | projects, teams, workflows, ai | RW — runs projects/tasks | ✅ `contributor@test.octopi.dev` | ✅ (team-attached) |
| **volunteer** | member | projects, teams, workflows, ai | RW — volunteer work, same sidebar as contributor | ✅ `volunteer@test.octopi.dev` | ✅ (team-attached) |
| **sponsor** | viewer | transparency, sponsorship, donations, grants | RO — the donor | ✅ `sponsor@test.octopi.dev` | ✅ |
| **auditor** | viewer | transparency, sponsorship, donations, grants | RO — governance, same sidebar as sponsor | ❌ | ✅ |
| **board_member** | member | full admin set | RW — strategic oversight | ❌ | ✅ |
| **adviser** | viewer | ai, finance, projects | RO — guest on a *personal* workspace (accountant/family) | ❌ | ✅ |
| **agentic** | admin | varies by agent type | RW — AI agents, created programmatically | ✅ `agentic@test.octopi.dev` | ❌ (never invited) |
| **private** | owner | ai, finance, projects, settings, teams | RW — solo on a *personal* workspace | ✅ `personal@test.octopi.dev` | ❌ (auto-created; gated by `feature.personal_space`) |

> **Sidebar rendering — the "Work" section (2026-07 rework, literacyseed #424).** `visible_sections` above are the **backend keys** (`workspace_role_policy.py`) and are unchanged. The frontend now *groups* the `projects` + `teams` keys under a single **"Work"** sidebar section — **My Work** (`/w/:seedId/my-work`, personal assigned-task inbox), **Projects** (`/w/:seedId/projects`, workspace-wide board; clicking a project opens `/teams/:teamId/:seedId`), **Teams** (`/w/:seedId/teams`, index) — plus Workflow/Feed when their flags are on. The old standalone "Teams" section + inline team list are gone. When asserting a persona's sidebar, look for the **Work** heading containing these, not a top-level "Teams" entry.

Seed all six seeded personas with:
```bash
docker exec compose-web-1 python manage.py seed_personas --workspace-id <UUID> --password testpass123
```
`auditor`, `board_member`, `adviser` are real and invitable but **not yet seeded** — they're documented here but the harness won't drive them until `seed_personas` provisions them. (Tracked as a follow-on; see `/gtm-qa-sweep` "Extending coverage".)

---

## 3. Capability map — allow vs *correctly-denied*

This is the spec the journey matrix asserts against. "Denied" rows are **expected behaviour**; the harness proves them, it doesn't flag them.

### admin / owner — the operator
- **CAN:** create/configure the workspace; verify the org (admin-verification); invite + manage members and roles; create recipients, publish needs; create projects/tasks; record donations; manage budget + categorize transactions; generate funder reports; write/send newsletters; configure AI agents; manage billing.
- **CORRECTLY DENIED:** nothing inside its own workspace. (Cross-workspace it has no rights.)

### contributor / volunteer — the team member
- **CAN:** see + work the projects/tasks/Kanban they're on; comment; move tasks; use AI assist on their surfaces; team chat; read workspace content.
- **CORRECTLY DENIED (assert these):** Finance/Budget surfaces (no `finance` section); Fundraising/Sponsorship/Donations/Grants admin surfaces; workspace Settings/billing; member-role management. Direct-navigating to `/budget/...`, `/sponsorship/...` admin, or `/settings?scope=workspace` must bounce.

### sponsor — the donor (deep dive: `/sponsor-persona`)
- **CAN:** browse public recipients/projects/campaigns/events; sponsor a recipient or project; donate (Stripe); view *own* "My sponsorships / My giving / Receipts"; read transparency (where my money went); pause/resume/cancel a recurring sponsorship; comment on impact updates.
- **CORRECTLY DENIED (assert these):** any workspace write — no recipient/project/task/budget creation, no member management, no settings, no internal finance ledger. Sees `transparency, sponsorship, donations, grants` ONLY. Direct-navigating to `/dashboard` admin widgets, `/transactions/...`, `/settings` must bounce.

### auditor — governance read-only
- Same surface as sponsor (`transparency, sponsorship, donations, grants`), but the *intent* is independent verification, not giving. Same deny set as sponsor.

### board_member — oversight
- Full admin sidebar (RW). For QA, treat as a second admin lens but note it's invitable as `member` role — confirm role→section resolution still yields the full set.

### private — solo personal workspace (gated)
- **CAN:** personal finance/budget, personal projects, AI, settings on their OWN personal workspace.
- **CORRECTLY DENIED:** all org-revenue surfaces (no fundraising/sponsorship/donations/campaigns/grants). Gated behind `feature.personal_space` — only drive when the flag is on.

### adviser — guest on a personal workspace
- RO guest (accountant/family). Sees `ai, finance, projects` on the *host's* personal workspace. Deny: settings, teams, any write.

### agentic — AI agents
- Not a human login path for journeys; covered by the agents surface (findings → Agents Kanban). The harness checks the *human-visible* output of agentic activity, not an agent "logging in."

---

## 4. Floor-level user stories — the real day-in-the-life flows

**These are NOT "does the sidebar render" checks.** A sidebar loading proves RBAC, not that the product works. The real test is the **floor walk**: every section has a *floor* (its tabs, its create flows, its detail screens, its money path), and the user stories below walk those floors the way a real admin or sponsor does — create, publish, discover, pay, update, verify. This is what surfaces the bugs a dashboard-load never reveals, and it's what `/gtm-qa-sweep` drives. Focus personas: **admin + sponsor** (the money + transparency loop is the product's whole reason to exist).

Each step is a concrete action with a **✅ verify**. 💳 = real Stripe **test** card step. 🔁 = the step where we check real-time vs refresh.

### 4.1 ⭐ FLAGSHIP — the admin↔sponsor transparency loop (drive this end-to-end)

This is THE journey. It's the user story the platform is sold on: a sponsor gives, and *sees where it went, as it happens*. Drive it as one continuous flow across both personas.

**Stripe-test env (decided 2026-06-29):** the **demo** (`c0d3henry@gmail.com`, Stripe-test-ready — Connect set up, test cards work). On the demo, c0d3henry is the workspace member, so admin actions and the sponsor/donor checkout run under that account (two-persona separation is simulated; the money + content + transparency mechanics are real). On localhost the personas are genuinely separate (`admin@`/`sponsor@`) but Zaylan needs a real test Connect account onboarded first (see `docs/payments/LOCAL_STRIPE_WEBHOOKS.md`) before checkout can complete. Never a live card; confirm `STRIPE_MODE=test`.

**⚠️ PRECONDITION — be in a TEAMSPACE, not a personal workspace.** Sponsorship / recipients / fundraising are **org** surfaces. Before any step, confirm the active workspace is a **Teamspace** (e.g. Zaylan), not a personal/"Circle" workspace — switch via the workspace switcher if needed. The nav hides Fundraising on personal workspaces, but the `/sponsorship/<ws>` route is NOT workspace-type-gated (you can direct-nav and even create a recipient on a personal workspace — see triage F5). Creating org data on a personal workspace is wrong; the harness must assert teamspace context first, not trust the active workspace.

**⚠️ RECIPIENT SELECTION (Henry, 2026-06-29):** when testing the sponsor checkout, **only pick a recipient that has NOT been sponsored before** AND that **has a sponsorship plan / donation form configured.** An already-sponsored recipient has no fresh SPONSOR button (expected, not a bug). A recipient showing *"No sponsorship plans yet"* has no plan/form → **un-sponsorable** (triage F6) → the checkout dead-ends. Seed data may have NO recipient that is both un-sponsored AND configured — so the loop's step 1 **creates its own** recipient and step 1b **configures its plan/donation form**, guaranteeing a sponsorable target.

1. **Admin — add a recipient.** Sponsorship ▸ Recipients ▸ **ADD RECIPIENT**. It's a **3-step wizard**: (1) profile — First name (req), Last name (req), story, photo; (2) location + contact email + an **auto-proposed Default Budget** to review; (3) **needs & impact** — an Estimated-needs table (recipient goal = sum of needs), highlighted categories, and the **donation-form / checkout** option (see step 1b). **Save and continue** between steps; **SUBMIT RECIPIENT** at the end. ✅ recipient appears in the grid with a goal bar + SPONSOR badge.
   - ⚠️ harness notes: the "Save and continue"/"SUBMIT RECIPIENT" buttons are rendered twice (hidden responsive duplicate) — click `nth(1)` / the visible one. The wizard **persists incrementally** across Save-and-continue: the recipient can be created even if the final SUBMIT errors "required" on an empty need-row (triage F4) — so a created-but-goalless recipient is possible; verify the goal is actually set.
1b. **Admin — attach a donation form (custom donation tiers / fees).** In wizard step 3 (or later from the recipient detail), publish a **donation form** for this recipient's checkout — admins define custom donation **tiers / amounts / cover-fee options** that the sponsor sees at checkout. ✅ the form's tiers render on the recipient's public sponsor/checkout page and drive the amount options in step 5. (This is the `donation_forms` surface tied to a recipient; gated by `feature.donation_forms` — confirm it's on for the workspace.)
2. **Admin — set the recipient's needs / goal** (complete at least one need row: title + estimated cost) so there's something concrete to fund. ✅ goal amount (sum of needs) shows on the card.
3. **Admin — publish / make discoverable.** Confirm the recipient is public (not "Hide recipient profile"). Grab the **sponsorship link** (per-card "Copy sponsorship link"). ✅ the public recipient page renders with **both** `child_id` and `seed_id` in the URL (missing either → "recipient unavailable").
4. **Sponsor — discover.** As the sponsor/donor, open Recipients (sponsor sidebar ▸ Transparency ▸ Recipients), find the new recipient, open the profile. ✅ story + needs + goal render; no internal/admin controls visible.
5. **Sponsor — sponsor them.** Click SPONSOR → pick amount + frequency (one-time / monthly) → checkout. 💳 Stripe **test card** `4242 4242 4242 4242`, any future expiry, any CVC. ✅ checkout succeeds; redirect to a thank-you/receipt; the recipient card's "raised" total increments and badge flips to SPONSORED.
6. **Sponsor — verify the giving record.** Transparency ▸ My giving / My sponsorships shows the new sponsorship (with pause/resume/cancel for recurring); Receipts ▸ a downloadable receipt exists for this payment. ✅ amounts match what was charged.
7. **Admin — post an impact update** on that recipient (recipient detail ▸ updates / "post update" — text + optional photo). ✅ update saves and appears on the recipient's update feed.
8. 🔁 **Sponsor — receive the update.** Back in the sponsor's transparency view of that recipient, the impact update appears. **Verify the delivery mechanism honestly:** does it show **live** (without a manual refresh — WebSocket/SSE), or only **after refresh** (polling/manual)? Real-time observability (Django Channels) was *queued, not shipped* as of this writing — if the update only appears on refresh, that's the current truth and a gap against the "real-time" promise, not a pass to gloss over.
9. **Sponsor — see where the money went (transparency).** Transparency ▸ My impact / the recipient's ledger: the donation → allocation → spend chain renders. ✅ the sponsor can trace their gift; nothing is unaccounted for (the headline differentiator).

**Variants of the same loop (drive at least one each):**
- **Sponsor a project** (recipient → project): sponsor sidebar ▸ Projects → open → sponsor/checkout 💳.
- **Sponsor a campaign**: Fundraising ▸ Campaigns (admin creates) → sponsor sidebar ▸ Campaigns → donate 💳.
- **Sponsor an event**: Fundraising ▸ Events (admin creates an event/gala) → sponsor sidebar ▸ Events → register/donate 💳.

### 4.2 Admin floor walks (every section's floor, not just the dashboard)

- **Sponsorship floor** — tabs: Recipients, Sponsorships, Campaigns, Events. Per-recipient card actions to exercise: Update photo, Edit, Invite sponsor, Copy sponsorship link, Hide profile, Delete. ✅ each opens/acts; "Invite sponsor" sends/produces an invite.
- **Projects floor** — create a project → add Kanban columns → add a task → assign it → comment → move it across columns → (if `feature.time_tracking`) start/stop a timer. ✅ each persists; board state survives reload.
- **Finance / Budget floor** — Budget dashboard (balance math renders, no NaN), Transactions (list + create + categorize a transaction + link to recipient), Reports (generate a funder report; if `feature.ai_reports` off, expect the manual path). ✅ books-balance figures are coherent.
- **Content / Newsletters floor** — Writing ▸ Drafts (create + AI-draft if `feature.ai_writing`), Newsletters (compose → send test → schedule/send), Subscribers, Templates, Library. ✅ draft persists; **do not blast real email** in a sweep.
- **Settings floor (lots here — walk every tab)** — Workspace Settings: Personal Info, Payment Methods, **Admin Verification** (KYC upload surface), Permissions/Members (change a member's role), Workspace profile, Billing/Plan, Integrations, Notifications preferences. ✅ each tab loads and its primary action works; role change reflects in the target member's `visible_sections`. ⛔ a non-admin hitting Settings bounces (asserted-deny).
- **Teams / Members floor** — invite a contributor + a volunteer (persona invite, magic link) → accept → confirm membership row + sidebar. ✅ invite → accept → member appears.

### 4.3 Sponsor floor walks (the whole Transparency floor)

Sponsor sidebar ▸ Transparency sub-nav, every item: **My impact** (where my money went — the ledger/impact view), **My sponsorships** (active list + pause/resume/cancel a recurring one), **My giving** (cross-workspace giving history), **Receipts** (download a PDF, scoped to this payer), **Recipients / Projects / Campaigns / Events** (discover + sponsor each 💳). Plus: comment on an impact update; ⛔ direct-nav any admin/finance/settings URL → access-denied panel, no data leak.

### 4.4 Contributor / volunteer & Private (lighter — RBAC + their own floor)

- **Contributor / volunteer** — see only Contacts + Teams; open a project board they're on, pick a task, comment, move it; ⛔ finance/fundraising/settings/sponsorship direct-nav bounces. (volunteer ≡ contributor sidebar; distinct data.)
- **Private** — personal Budget + Projects on their own workspace render; Finance is *allowed* (own); ⛔ no org-revenue (fundraising/sponsorship/donations/campaigns/grants) anywhere. Gated by `feature.personal_space`.

---

## 5. How this skill is consumed

- **`/gtm-qa-sweep`** reads this skill's capability map + user stories and the matrix doc to drive Playwright journeys, asserting allow AND deny per persona.
- **Adding a persona-specific surface?** Update the capability map here AND add a matrix row, or the coverage check in `/gtm-qa-sweep` will flag the gap.
- **A new sidebar section** must declare which personas see it (update §2 `visible_sections`) — the matrix is generated against `visible_sections`, so an uncovered section fails the matrix on purpose.

When in doubt about whether a denial is a bug: re-read §1. If the user's `role` shouldn't permit it, the deny is correct and the journey should *assert* it.
