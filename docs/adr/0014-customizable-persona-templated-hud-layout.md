# ADR 0014 — Customizable, Persona-Templated HUD Layout

**Status:** Proposed (design only — build held pending Tom validation of the persona template set)
**Date:** 2026-08-03
**Deciders:** Henry (+ design partners Tom, William)
**Related:** ADR 0007 (red/blue teams as real teams), ADR 0009 (compliance lens),
[[project-tom-operator-feedback]], [[project-william-operator-feedback]] (the operator convergence
that motivates this), per-workspace branding (FE #95).

---

## 1. Context

Two design-partner operators independently asked for the same thing: **let each operator arrange the
command center to their own job**, and ship **sensible per-role defaults** so a new user isn't staring
at a wall of 50 cards.

- **Tom:** per-user / per-team **show / hide / reorder / sort-by** cards + **pre-seeded persona
  templates** (the macOS-desktop metaphor — arrange freely, or "Sort By / Clean Up / Stacks").
- **William:** lead with a ranked *"what do I need to know today"* digest and **suppress the rest** —
  the layout is how you suppress the rest.

### What already exists (verified 2026-08-03)

| Capability | State |
|---|---|
| Drag-to-move + corner drag-to-resize on every card | **Built** (`DraggablePanel`, `panelOffsets`/`panelSizes`, `resizeProps`) |
| Layout persistence | **localStorage only** (`cc-v2-panel-offsets` / `cc-v2-panel-sizes`) — per-browser, per-device, wiped on cache clear, **not tied to the user account** |
| Branding + colours | **Built** — `Settings ▸ Branding` → `--hud-accent`, logo, blue⇄red (FE #95) |
| `@dnd-kit/core` + `sortable` | **Installed** (0 new deps for reorder / show-hide) |
| `react-grid-layout` (free-form resize/pack) | **Not installed** |
| Persona system | **Exists** — membership `persona` ∈ {`admin`, `auditor`, `contributor`} (+ the red/blue/comply team lens, ADR 0007) — the natural key for templates |
| Per-user preference persistence precedent | `notifications/userpreferences` model exists |

### The gap

There is **no backend-persisted, per-user layout**, **no show/hide**, and **no templates**. A layout
does not follow the user across devices or logins, and there are no role defaults. That is the unbuilt
half of the operator ask.

---

## 2. Decision

Introduce a **backend-persisted, precedence-resolved HUD layout** with **persona templates**, built on
the existing drag/resize + dnd-kit, migrating persistence off localStorage.

### D1 — A `HudLayout` is per (user × workspace), backend-persisted

A layout document is scoped to **user × workspace** (an operator can arrange the same workspace
differently than a teammate, and differently across workspaces). It persists **server-side** so it
follows the user across devices/logins. localStorage is retained only as a **fast/offline cache**, no
longer the source of truth. This is the concrete form of Tom's "persisted role-based saved views."

### D2 — The layout document is a small, versioned JSON schema

```jsonc
{
  "version": 1,
  "template": "soc_analyst",          // which persona template this derives from (or "custom")
  "panels": [
    { "id": "today",      "visible": true,  "order": 0, "offset": {"x":0,"y":0}, "size": null },
    { "id": "compliance", "visible": false, "order": 1, "offset": {"x":0,"y":0}, "size": {"w":320,"h":240} }
    // …one entry per known panel id
  ]
}
```

Unknown/new panel ids fall back to their template/default entry (forward-compatible — adding a card
never breaks a saved layout). `size: null` = auto. A `version` field allows migration.

### D3 — Resolution precedence: user override → persona template → system default

At render time the effective layout is resolved in order:

1. the user's saved `HudLayout` for this workspace (if any), else
2. the **persona template** for the user's membership `persona` / team lens, else
3. the **system default** layout.

Per-panel, a user override wins; where the user hasn't touched a panel, the template value applies.
"**Reset to template**" clears the user override and falls back to (2).

### D4 — Persona templates are seeded, keyed off the existing persona/team system

Ship a **small, opinionated set** of default templates keyed off the membership `persona` (and the
ADR-0007 team lens defend/attack/comply), e.g.:

- **SOC analyst / contributor** → TODAY digest, findings, alerts, attack surface up top; branding/prompt-quality hidden.
- **Manager / admin** → risk score, compliance, coverage, cost — the exec KPIs (William: don't drown the manager in raw findings).
- **Auditor / comply lens** → compliance frameworks, evidence, attack coverage foreground.

The exact per-persona card sets are the **primary open question for Tom** (see §5) — the *mechanism*
is decided here; the *content of the seed templates* is validated before build.

### D5 — Show/hide + reorder ride the installed dnd-kit; free-form grid is a pinned phase 2

Reorder + show/hide + a "sort by / clean up" action are built on the **already-installed `@dnd-kit`**
(0 new deps, shared with the kanban dnd work). **Free-form grid resize/packing** (`react-grid-layout`)
is deferred to a later phase and, if adopted, is **pinned to an explicit version** (pin-versions rule)
— it is not required for the core win.

### D6 — Explicit Architecture placement

- **ORM model** `HudLayout` (user FK, workspace FK, `template`, `document` JSON, timestamps) under
  `infrastructure/persistence/…`. It is presentation-preference state, not a domain aggregate.
- A **`HudLayoutStorePort`** (application layer) with an ORM adapter; a **CQRS read** returns the
  *resolved* effective layout (user override merged over template over default) so the controller stays
  thin and the merge logic is testable framework-free.
- The **persona → template** mapping is a policy in the application layer (a provider/policy), not
  hard-coded in the controller or the frontend.
- Templates themselves are **seed data** (a management command, like `seed_subscription_tiers` /
  `seed_feature_flags`) so they're reproducible and versioned.
- Gate the whole feature behind a **feature flag** (`feature.hud_layout_customization`) per the
  day-one flag discipline.

### D7 — Branding stays where it is

Colour/logo (FE #95, `Settings ▸ Branding`) is **out of scope** — it already works and is workspace-level,
not per-user-layout. This ADR is purely about **card arrangement + visibility + templates**.

---

## 3. Consequences

**Positive**
- A layout follows the user across devices — the actual "persisted role-based saved views" Tom asked for.
- New users land on a **sensible per-role default**, not a wall of cards (William's "suppress the rest").
- Built almost entirely on parts we already own (DraggablePanel, dnd-kit, persona system, userpreferences precedent, seed-command pattern) — small dependency surface.
- Forward-compatible: adding a new HUD card never breaks a saved layout (D2 fallback).

**Costs / risks**
- One new model + migration + a store port + CQRS resolver + a seed command + frontend save/load wiring.
- **Template-set risk:** wrong default templates are worse than none (a manager seeing a contributor's wall). Mitigated by validating the seed set with Tom **before** build (§5) — this is why the build is held.
- localStorage → backend migration must be graceful (no layout loss on first load post-deploy): treat an existing localStorage layout as an implicit user override to import once.

---

## 4. Phased build plan (held — do not start until §5 is validated)

- **P1 — Persistence + show/hide/reorder (the core win).** `HudLayout` model + migration, `HudLayoutStorePort` + adapter, resolve-CQRS (user→template→default merge), save/load API, feature flag. Frontend: migrate drag/resize off localStorage to the API, add show/hide + dnd-kit reorder + "reset to template." Query-count guard + resolver unit tests.
- **P2 — Persona templates.** Seed command for the validated template set, a **template switcher** in the HUD, "reset to template," persona→template policy. Onboarding lands the user on their persona default.
- **P3 (optional) — Free-form grid.** `react-grid-layout` (pinned) for free resize/packing; only if P1/P2 validate the appetite.

## 5. Open questions to validate with Tom BEFORE building (why the build is held)

1. **The seed template set** — which personas, and **which cards each shows/hides by default** (the D4 content). This is the single highest-risk decision and the reason to validate first.
2. **Scope of "team" vs "user"** — do teams/admins get to define a shared team template that members inherit (adds a team-level layer above the persona template), or is it purely persona-default + per-user override for v1?
3. **Sort-by / Clean-up semantics** — is "Sort By" a transient view (like macOS) or does it persist as the new order?
4. **Free-form grid appetite** — is drag/resize/reorder/show-hide enough (P1/P2), or is `react-grid-layout` free-form packing (P3) actually wanted?

Per William's "validate before overbuilding," P1 does not start until at least Q1 is answered.
