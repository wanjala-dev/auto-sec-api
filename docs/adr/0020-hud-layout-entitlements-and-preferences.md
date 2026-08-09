# ADR 0020 — HUD desk cards as governed features: a narrowing entitlement chain (platform → workspace → team) composed with a most-specific-wins layout preference (persona template → user)

Status: Proposed (2026-08-08) — **design only; build deferred** until Henry's go per phase, and
sequenced behind the standing "harden the core loops for Tom's real use" priority.

Relates to: **ADR 0014** (customizable persona-templated HUD layout — an OPEN design PR, api#230;
this ADR **extends D1/D2/D5/D6/D7 and supersedes D3**, clause by clause in §Relationship), **ADR
0007** (red/blue teams as real teams — the team lens this design deliberately does *not* make an
authority tier in v1), **ADR 0011** (sample-data mode — the only existing customer-facing flag write,
and the shape the workspace write API copies), **ADR 0002** (persona is never a permission input —
persona templates are preference defaults, never entitlements), **ADR 0004** (Finding SSOT — the
capabilities being entitled are the pillars that feed it), and the operator record (Tom and William
both asked for customizable, persona-templated layouts and "what do I need to know today":
`project-tom-operator-feedback`, `project-william-operator-feedback`).

## Context

### Henry's ask

Dictated 2026-08-08, in his framing:

> "I know the layout with the cards is just right now being done on the front end and that's OK, but
> I do think this is something we need to actually connect to feature flags — which features someone
> turns on and off, for either the user or the workspace. When a workspace admin [sets something],
> obviously that overrides the user turning that card on. I just want to figure out a way to
> translate these cards into features that a workspace admin or user [can control] — but obviously
> WE, the owner of the entire system, control which feature flags are turned on for which workspace;
> then the workspace admin controls which feature flags are on for that workspace; then that team;
> then a user can manage their own layout features as well."

So: **platform → workspace → team → user**, upper tiers overriding lower ones.

### Why now

Three things converged. (1) The desk-card layout shipped as a pure-frontend localStorage toggle
(fe#151/#152/#154) and is already load-bearing in demos. (2) ADR 0014 designed the persistence layer
but left its §5 Q2 open — *"do teams/admins get to define a shared team template that members
inherit… or is it purely persona-default + per-user override for v1?"* — which is exactly the
question Henry just answered with a hierarchy. (3) The shipped v1 has a real bug that any
server-side design fixes for free: `cc-v2-panel-visible` / `cc-v2-panel-offsets` /
`cc-v2-panel-sizes` are **not namespaced by user or workspace**, so one browser profile is one desk
across every workspace and every logged-in account. Tom running two workspaces hits that on day one,
entitlements or not.

### The tension this ADR exists to resolve — read this before anything else

**Auto-Sec's existing feature-flag precedence is the exact inverse of what "an admin overrides a
user" requires, and the inversion is deliberate and load-bearing.**

`evaluate_feature_flag` resolves **user → workspace → plan tier → global → default**, short-circuiting
on the first active rule
(`components/shared_platform/infrastructure/services/feature_flags.py:154-157`; user branch `:199-211`,
workspace branch `:213-229`, plan tier `:231-241`, global `:243-254`, default `:256-257`). A
`USER`-scoped rule with `enabled=True` beats a `WORKSPACE`-scoped rule with `enabled=False`. That
ordering is locked by
`components/shared_platform/tests/integration/test_core_feature_flags.py:19-52`, and it is *correct
for what those flags are*: an operator-escalation mechanism. `feature.support_impersonation` is
documented as "Per-user enable rule expected; never globally enabled"
(`components/shared_platform/cli/management/commands/seed_feature_flags.py:43-48`), and
`PROD_ALLOWLISTED_USER_FLAGS` (`:136`) exists precisely so a named user can be let past a global
disable. **Flipping USER below WORKSPACE would silently break both.**

The resolution is not to reorder one ladder. It is to recognise that Henry described **two different
kinds of setting** and the industry runs them as two engines pointing opposite directions:

| | **Entitlement / capability** | **Preference** |
|---|---|---|
| Question | *"Does this account have the right to this capability at all?"* | *"How does this person want their desk arranged?"* |
| Tiers | platform → workspace → team | persona template → user |
| Direction | **narrowing** — a lower tier can never grant what an upper tier withheld | **most-specific-wins** — the nearest setting fills in |
| Owner | product / billing / workspace admin | the individual |
| Auto-Sec today | partially: `GLOBAL` rule + the (inert) plan-tier layer | the existing user→workspace→global ladder, and `cc-v2-panel-visible` |

Grafana is the cleanest external proof that one product runs both: preferences cascade
Server → Org → Team → User where **"the lowest level always takes precedence"**[^grafana-prefs],
while access is a wholly separate ACL system on the dashboard/folder object[^grafana-perms]. Same
product, two engines, opposite precedence.

The candidate formulation in the brief — `entitled(platform) AND enabled(workspace) AND
allowed(team) AND NOT hidden_by(user)` — **survives testing and is adopted** (D3), with one
correction the adversarial review forced: it cannot be expressed by `FeatureFlagRule.enabled` as it
stands, because that field carries *override* semantics (a `True` at a lower tier re-grants), not
*conjunction* semantics. D4/D5 make the narrowing tiers structurally deny-only so the invariant is
enforced by the write API rather than promised by a docstring.

### Build sequencing (standing constraint)

This is design. Nothing here is built until Henry says go, phase by phase, and it queues behind
hardening AWS connect→scan, GitHub connect→scan, and the draft-PR loop for Tom's real use.

## Research grounding (claim → source, fetched 2026-08-07/08)

| # | Claim | Source |
|---|---|---|
| R1 | **The flag/entitlement split is a systems split, not a naming one.** A feature flag answers "is this code path safe to run now?" (engineering-owned, short-lived); an entitlement answers "does this account have the contractual right?" (product/billing-owned, permanent). | Featureflow[^ff-vs-ent]; Kaiten[^kaiten] |
| R2 | **LaunchDarkly itself treats entitlements-on-flags as an advanced pattern** requiring a single upstream source of truth (billing) synced *into* flags, plus audit logging, and warns that frequent entitlement changes risk incorrectly billing a customer. | LaunchDarkly (2020-01-28)[^ld-entitlements] |
| R3 | **No flag vendor implements a narrowing chain; every one is most-specific-wins.** LaunchDarkly: individual targeting beats rules beats default[^ld-targeting]. Flagsmith: "identity overrides always take precedence over segment overrides"[^flagsmith]. Statsig: ID overrides return *before* rule evaluation[^statsig]. Copying flag-vendor precedence reproduces the inversion we already have. | [^ld-targeting][^flagsmith][^statsig] |
| R4 | **Narrowing, where it exists, is expressed as AND-composition, not as a re-ordered ladder.** Unleash constraints AND together within a strategy[^unleash]; LaunchDarkly *prerequisites* gate a flag before targeting runs[^ld-targeting]; AWS SCPs "do not grant permissions" at all — the effective permission is the **intersection** from root → OU → account[^aws-scp]. | [^unleash][^ld-targeting][^aws-scp] |
| R5 | **The canonical answer to "admin beats user" is a per-key enforcement mode, not a reordered chain.** Chrome Enterprise: mandatory policies "force the setting and do not allow the user to change them", recommended ones are changeable defaults, and "a mandatory policy still overrides a recommended policy"[^chrome]. Windows Group Policy: Policies are enforced, Preferences are changeable defaults, and where both define a setting **the policy wins**[^gpp]. | [^chrome][^gpp] |
| R6 | **Over-modelling enforcement states is a known failure.** Apple MCX shipped three enforcement frequencies (Once / Often / Always); modern configuration profiles collapsed to *Always*. | Bresink MCX docs[^mcx] |
| R7 | **Hierarchy does not imply narrowing.** Google Workspace OUs are *nearest-OU-wins*: a child OU can override the parent, including turning a service back on, and the console labels each setting **Inherited / Overridden**. A hierarchy must state its direction explicitly. | Google Workspace Admin Help[^gws-ou] |
| R8 | **Managed settings are surfaced, not hidden.** Slack renders a lock icon on org-locked preferences; Notion tells workspace owners a setting is "managed by your organization". | Slack[^slack-lock]; Notion[^notion-org] |
| R9 | **Entitlements are derived from billing, never hand-set per user.** Stripe attaches features to *products*; subscribing auto-creates the customer's `ActiveEntitlement`. There is no user tier that can override it. | Stripe Billing/Entitlements[^stripe-ent] |
| R10 | **Nobody entitles a dashboard widget.** Grafana permissions the dashboard/folder object[^grafana-perms]; Datadog permissions the dashboard resource via `restricted_roles` / Restriction Policies (and per-dashboard *view* restriction is itself a gated paid feature)[^dd-rbac][^dd-restrict]; Wiz scopes by role × project/tenant[^wiz-roles]. Effective widget visibility falls out of (a) data-scope permissions and (b) user layout choice. **Empty-set finding: no B2B security/observability product surveyed models individual widgets as entitlements.** | [^grafana-perms][^dd-rbac][^dd-restrict][^wiz-roles] |

## Decisions

### D0 — Two engines, opposite directions, never merged. Do **not** invert the existing resolver. **[proposed]**

Entitlement narrows; preference chooses within it. Concretely:

- The existing `evaluate_feature_flag` ladder stays byte-for-byte as it is for every flag that
  exists today. `test_core_feature_flags.py:19-52` stays green unmodified; `feature.support_impersonation`
  and `PROD_ALLOWLISTED_USER_FLAGS` keep user-beats-global.
- Capability entitlement is a **second evaluation function over the same registry and the same rule
  table**, selected per key by a discriminator (D4). One flag registry, one rule table, two
  algorithms — not two flag systems (`dry-reuse.md` §4: one canonical thing per concern).
- Layout preference does **not** live in `FeatureFlagRule` at all (D4).

**Rejected here, explicitly: reordering the ladder so workspace beats user.** It is a one-line change
that looks like it satisfies Henry's ask and silently breaks the two operator-escalation mechanisms
that depend on the current order.

### D1 — Capabilities are entitled; cards are preferences. The card↔capability map is many-to-many, backend-owned, and lives in the shared kernel. **[proposed]**

**We do not put entitlement rules on desk cards.** R10 is an empty-set finding across the products
we compete with, and card-level rules would multiply the rule surface by `|DESK_PANELS|` (16 today)
inside a *global* key namespace shared with `feature.ai_kill_switch`. Instead:

- The entitled unit is a **capability key that already gates the data**, e.g. `feature.code_security`
  (`components/code_security/api/controller.py:19`), `feature.cloud_posture`
  (`components/integrations/api/controller.py:186`), `feature.cloud_asset_graph`,
  `feature.container_security` (`components/container_security/api/controller.py:52,97`).
- A card declares which capabilities it *reads*. `codeRepos → [feature.code_security]`.
  `attackSurface → [feature.cloud_asset_graph]`. A card whose list is **empty** is vacuously
  entitled and is pure preference — `clock`, `modules`, `leftPanels`, `incomeTrend`
  (`auto-sec-frontend/src/components/V2/v2Constants.js:458-482`).
- The mapping is **many-to-many in both directions**, and both directions occur today:
  `feature.container_security` has **no card of its own** (it surfaces inside `activeScans`), and
  `rightPanels` is **one card over four capabilities**.

**Catalog ownership:** `components/shared_kernel/domain/desk_catalog.py` — a flat frozen module
alongside the existing `mitre.py` / `tagging.py` catalogs. It is shared vocabulary between the
context that owns layout (`identity`, D4) and the context that owns flags (`shared_platform`), and
Rule 3 of the architecture manifesto permits exactly this cross-context dependency shape. The
frontend `DESK_PANELS` becomes a **mirror asserted by a contract test**, not a second source of
truth.

**Hard prerequisite, not optional polish:** `rightPanels` currently renders LIVE RUN, CLOUD POSTURE,
FINDINGS, ASSET GRAPH and ATTACK COVERAGE under one draggable id
(`auto-sec-frontend/src/features/agents/presentation/pages/CommandCenterV2Page.jsx:4838-4903`). Any
card→capability map is dishonest until it is split into separate ids. Every candidate model and all
three reviewers named this independently.

**Second prerequisite:** `V2_PANEL_REGISTRY` declares `requiresAdmin: true` for `promptQuality`
(`v2Constants.js:497-504`) and **nothing anywhere enforces it** — `grep -rn requiresAdmin src/` hits
only that file. It becomes real or it is deleted; dead authority metadata in an authority design is
a landmine.

### D2 — Entitlement is a **product** control, not a security boundary. **[proposed]**

The resolved desk decides what the HUD *renders*. It never decides what the API *serves*. Every
capability keeps its independent server-side gate — `RequiresFeatureFlag`
(`components/shared_platform/api/permissions.py:51-94`) or the inline `is_feature_enabled(...)` call
the pillar already makes — so a stale or hostile client that renders a restricted card still gets a
403 from the data endpoint and leaks nothing.

Corollary worth stating because it is a real product consequence, not a footnote: because a
restriction is written on the **same key** the endpoint reads, a workspace admin restricting
`feature.cloud_posture` does not merely hide a card — it stops cloud-posture scans for that
workspace. One key, no divergence, and no second "UI-only" flag namespace. Whether that is the
desired blast radius is **OQ6**.

### D3 — Resolution algorithm. **[proposed]**

Two resolutions, composed by one AND. Tri-state per entitlement tier (`ALLOW` / `DENY` / `UNSET`) so
"no rule" is a defined value rather than an implicit boolean.

```
# ─────────────── ENTITLEMENT (narrowing; server-authoritative) ───────────────
resolve_capability(cap_key, user, workspace) -> Decision:

    # T0 PLATFORM — the ceiling. Derived from billing; staff may override.
    #   GLOBAL rule (staff, Django admin) wins over the plan map, so a
    #   per-customer grant/kill is one row and needs no code deploy.
    if (r := active_rule(GLOBAL, cap_key)):        t0 = r.enabled
    elif cap_key in any TIER_FEATURE_MAP value:    t0 = cap_key in features_for_tier(plan_tier(ws))
    else:                                          t0 = flag.default_enabled
    if not t0:  return DENY(tier=PLATFORM)

    # T1 WORKSPACE — may narrow, never re-grant. (D5 makes this structural.)
    if (r := active_rule(WORKSPACE, cap_key, ws)) and not r.enabled:
        return DENY(tier=WORKSPACE)

    # T2 TEAM — INTERSECTION over every team the user belongs to in ws.
    #   NOT profile.active_team_id: active team is user-switchable (ADR 0007),
    #   so reading it would make the narrowing trivially escapable.
    for t in teams_of(user, ws):
        if (r := active_rule(TEAM, cap_key, t)) and not r.enabled:
            return DENY(tier=TEAM, team=t)

    return ALLOW

# ─────────────── PREFERENCE (most-specific-wins; ADR 0014 D3 intact) ─────────
resolve_preference(card, user, ws) -> PanelPref:
    return user_layout(ws).get(card.id)              \
        ?? persona_template(membership.persona).get(card.id) \
        ?? DESK_CATALOG[card.id].default

# ─────────────── THE COMPOSED READ (one CQRS query) ──────────────────────────
resolve_desk(user, ws) -> [DeskRow]:
    for card in DESK_CATALOG:
        dec  = first DENY over card.capabilities, else ALLOW    # AND over N caps
        pref = resolve_preference(card, user, ws)
        yield DeskRow(
            id = card.id, label = card.label,
            entitled          = dec.allowed,
            entitlement_tier  = dec.tier,        # PLATFORM | WORKSPACE | TEAM | None
            entitlement_cap   = dec.capability,  # which key denied it
            preferred_visible = pref.visible,
            visible           = dec.allowed and pref.visible,   # ← the invariant
            locked            = not dec.allowed,
            order = pref.order, offset = pref.offset, size = pref.size,
        )
```

**Precedence, in one sentence an operator can hold:** *a card shows if every capability it needs is
granted by your plan and not restricted by your workspace or by any of your teams — and you haven't
hidden it.*

**Absence semantics, stated once:** at an entitlement tier, no rule means **inherit**; a rule with
`enabled=False` means **final deny**; a rule with `enabled=True` at T1/T2 means **nothing** — which
is why D5 forbids writing one.

**`preferred_visible` is stored and returned separately from `visible`.** This is what makes
"restrict then re-enable" lossless: the user's choice is never overwritten by an entitlement change,
so their desk returns exactly as it was.

### D4 — Data model and architectural ownership. **[proposed]**

| Change | Owner context | ORM / location | Note |
|---|---|---|---|
| `FeatureFlag.kind ∈ {experiment, capability}`, default `experiment` | `shared_platform` | `infrastructure/persistence/core/models.py` | **The key, not the rule, selects the algorithm.** All 14 seeded flags stay `experiment`; the new code is inert on merge. |
| `FeatureFlagRule.Scope.TEAM` + nullable `team` FK | `shared_platform` | same | **Deferred to P4** — extend the three `UniqueConstraint`s and the `CheckConstraint` at `core/models.py:112-134` when it lands. |
| `resolve_capability()` / `resolve_desk()` | `shared_platform/application/` (capability) + `identity/application/` (desk read) | CQRS read; `CapabilityResolverPort` | see the cross-context note below |
| `DESK_CATALOG` (id, label, capabilities[], default) | `shared_kernel` | `components/shared_kernel/domain/desk_catalog.py` | frozen, framework-free; FE mirror contract-tested |
| `HudLayout` (user, workspace, doc JSON, version, updated_at) | **`identity`** | `infrastructure/persistence/identity/` | per-user, deleted with the user, **never admin-readable**. Keyed *by* workspace, not owned by it. `HudLayoutStorePort` per ADR 0014 D6. |
| Persona templates | `identity` seed data | seed command | preference defaults, never permissions (ADR 0002; `workspaces/models.py:347-355` — "NEVER read this in permission checks") |

**Cross-context resolution (a real question the review raised).** The desk read needs both the
layout (owned by `identity`) and the capability decision (owned by `shared_platform`). Reading
`identity`'s `HudLayout` ORM from a `shared_platform` query would be a cross-context infrastructure
import — forbidden by Rule 3. So **`identity` owns the desk read** (it already owns the user, the
profile, and the `me/summary` payload) and consumes capability decisions through the **existing**
`components/shared_platform/application/facades/feature_flags_facade.py` /
`application/providers/feature_flags_provider.py` seam. The shared vocabulary goes in the shared
kernel. No new cross-context seam is invented.

**Why layout must not be a `FeatureFlagRule`:** every write to that table fires the signal bridge
(`components/shared_platform/infrastructure/adapters/django_feature_flag_signal_bridge.py:24-36`) →
`bump_feature_flags_version()` → `cache.incr` on a **global** key
(`django_cache_feature_flag_adapter.py:25-32`). One operator hiding CLOCK would invalidate every
tenant's flag cache. It would also invert the meaning of `USER` scope for the 14 existing flags.

### D5 — Write API: narrowing tiers accept **deny or clear, never grant**. `manage_settings` gates it. The platform tier has no customer API. **[proposed]**

There is **no flag write endpoint today** — `FeatureFlagsView` and `FeatureFlagStatusView`
(`components/shared_platform/api/controller.py:125-187`) are both read-only `IsAuthenticated`, and the
only programmatic writer is `set_workspace_flag`
(`components/shared_platform/infrastructure/services/feature_flags.py:72-87`), reached over HTTP only
by the owner-gated sample-data toggle (ADR 0011). So this is net-new surface.

| Endpoint | Tier | Gate |
|---|---|---|
| `GET /identity/me/workspaces/<ws>/desk/` (also embedded in `me/summary`) | — | member |
| `PUT /identity/me/workspaces/<ws>/hud-layout/` | user preference | self only |
| `PUT /feature-flags/workspaces/<ws>/capabilities/<key>/` | workspace | `has_workspace_permission("manage_settings")` |
| `DELETE /feature-flags/workspaces/<ws>/capabilities/<key>/` | workspace (clear → inherit) | same |
| `PUT|DELETE /feature-flags/teams/<team>/capabilities/<key>/` (P4) | team | `manage_settings` — team lead is **not** sufficient; narrowing is a security decision |
| platform | `TIER_FEATURE_MAP` data edit + staff `GLOBAL` rule in Django admin (`infrastructure/persistence/core/admin.py:24-40`) | **staff only, no customer API** |

**The load-bearing constraint: `PUT` accepts `{"restricted": true}` and nothing else.** A request
attempting to *grant* is rejected 400 — *"capabilities are granted by your plan; workspace settings
can only restrict."* This is the single change the semantics reviewer identified as most improving
the design, and the reason is concrete: under a pure narrowing chain, `enabled=True` at T1/T2 is a
no-op, so an admin could create a rule, observe no effect, and file a bug. Making the API refuse it
turns a documented convention into an enforced invariant.

**`manage_settings` already exists and is unclaimed.** It is in `VALID_PERMISSION_KEYS`
(`components/membership/api/groups_controller.py:47`) and in the owner/admin bundles
(`components/workspace/cli/management/commands/seed_workspace_roles.py:76-77`), and a tally of every
`has_workspace_permission(...)` call site in `components/` shows no consumer. **Zero new permission
keys.**

Shape and audit are copied wholesale from `TriageCapabilityView`
(`components/integrations/api/controller.py:547-557`) + `SetWorkspaceAgentCapabilityUseCase`
(allowlist validation `:79-82`, bool coercion `:83`, audit `:114-136`), not reinvented.
`set_workspace_flag` is widened to take a scope rather than gaining a parallel writer (its one
caller is `components/sample_data/application/sample_data_service.py:33-46`).

### D6 — Audit: the toggle writes an audit row, and the platform tier needs a different record. **[proposed]**

**Feature flags have zero audit coverage today.** The signal bridge only bumps the cache version;
neither `FeatureFlag`/`FeatureFlagRule` nor `WorkspacePermissionGrant`/`WorkspaceGroup` produce an
`EntityAuditLog` row (`infrastructure/persistence/audit/models.py:35-89`; the complete set of
`log_field_change` call sites is four files). An admin disabling a security surface workspace-wide is
invisible. R2 makes audit a named requirement of entitlement-on-flags.

- Every capability write emits `log_field_change` with actor, previous/new, and reason — copying the
  `set_workspace_agent_capability_use_case.py:114-136` stance verbatim, including *"the flip must not
  be lost to an audit hiccup, but a silent audit gap is a governance defect — log loudly."*
- **Named gap:** `_infer_workspace_id` (`components/audit/infrastructure/services/audit_log.py:43-51`)
  makes the trail workspace-scoped, so a **platform-tier / GLOBAL** change has no workspace and
  produces no usable row. That tier needs a separate staff-audit record keyed to the flag. Out of
  scope to build here; named so it is not discovered later. (Backlog #95 already tracks broadening
  `EntityAuditLog` coverage — this rides that work.)

### D7 — Caching and invalidation. **[proposed]**

Reuse all three existing layers unchanged: the per-request dict (`feature_flags.py:90-97`), the Redis
key `feature_flags:v1:{key}:u:{uid}:w:{wsid}:v:{version}` (`:178-181`), and O(1) version-bump
invalidation.

- **No new cache-key dimension for teams.** The key already carries `u:{uid}`, and a user's team set
  is a function of (user, workspace) — so it is already keyed correctly *provided membership changes
  invalidate*. Add `m2m_changed` on `Team.members` and `post_save`/`post_delete` on `TeamMembership`
  to the existing signal bridge when P4 lands. A `t:{teamset_digest}` dimension was proposed and
  **rejected**: it is derivable, and it costs a per-request query for nothing.
- The desk read gets its **own** key, `desk:v1:u:{uid}:w:{ws}:v:{flag_version}:l:{layout_updated_at}`
  — so a layout save invalidates one user, never the fleet.
- **Merge-blocking prerequisite (P0):** the ladder is currently implemented **twice** —
  `evaluate_feature_flag:199-257` and `flags_for_context:343-359`. Adding a second algorithm on top
  of duplicated code ships **four** precedence implementations. Extract one pure
  `_resolve(flag, rules_by_scope, tier)` called by both, prove it inert against
  `test_core_feature_flags.py:19-52`, *then* add `kind`. This is `dry-reuse.md` §2 applied to an
  existing violation, and it is the reuse reviewer's single highest-value change.

### D8 — The server ships a **resolved** desk; the frontend computes no policy. **[proposed]**

`GET /identity/me/summary/` already embeds the evaluated flag map
(`components/identity/api/controller.py:481-487`) and the client refetches per workspace
(`auto-sec-frontend/src/features/feature-flags/presentation/useFeatureFlagsBootstrapPresentation.ts:132-198`).
That payload gains a `desk` array of `DeskRow` (D3).

- The render gate at `CommandCenterV2Page.jsx:2244-2247` becomes a single lookup of `row.visible`,
  and the **seven cards that call `deskPanelVisible()` outside `CONTEXT_PANELS`** (`:3985, 4047,
  4074, 4541, 4723, 4757, 4963`) route through that one helper. There are already two gating
  mechanisms; we consolidate rather than add a third.
- **Explicitly rejected: shipping the *inputs* and ANDing them in the browser** (a `requires: [...]`
  array on `DESK_PANELS`). That is a second source of truth for "is this entitled", it drifts the
  moment a capability key is renamed, and it is the wrong default posture for a security product.
- **Locked rows are shown, not hidden** (R8): in `LayoutSection.jsx` the row stays listed, toggle
  disabled, padlock, with the **server-authored** reason derived from `entitlement_tier` —
  *"Cloud Posture is turned off for this workspace by an admin. Your preference is saved — the card
  returns if it's re-enabled."* vs *"Cloud Posture isn't included in your plan."* + upgrade link.
  Authored once on the server, not guessed per frontend branch. **OQ7** asks whether an unpurchased
  capability should be advertised at all.

### D9 — Persona templates are **preference defaults**, and they are the half operators actually asked for. **[proposed]**

ADR 0014 D4 survives intact and is the seed layer of `resolve_preference`: templates keyed on
`WorkspaceMembership.persona` (admin / auditor / contributor) crossed with the ADR-0007 team lens
(defend / attack / comply), seeded as data, with "reset to template" clearing the user override.

Three constraints:

1. **A template is never an entitlement.** `workspaces/models.py:347-355` — *"NEVER read this in
   permission checks; use role instead. See ADR 0002."* A template proposes a starting desk; it
   cannot grant or withhold anything.
2. **Templates answer ADR 0014's §5 Q2 by splitting it.** Teams get *optionally* a **template** tier
   (a starting layout for Blue vs Red vs Comply — fallback semantics) and *separately, later* an
   **entitlement** tier (narrowing semantics, P4). They are not the same tier, and conflating them is
   what made that question hard.
3. **This leg has two operators on record and one live bug to fix; the entitlement chain has one
   requester.** The ops reviewer's point, adopted in the phasing (P1/P2 before P3): if the
   entitlement half slips behind the Tom-hardening priority, the half operators asked for is already
   live. Nothing is thrown away — the desk read already returns `visible` per card, so the
   entitlement half is later just an extra AND on a field the client already consumes.

### D10 — Migration from the shipped localStorage v1 (fe#151): nothing is lost, nothing is destroyed. **[proposed]**

On first authenticated load with **no** server `HudLayout` row and a **present** `cc-v2-panel-visible`,
the client POSTs the local doc once as the seed, sets a `cc-v2-layout-migrated-v2` marker, and treats
the server as SSOT thereafter (localStorage demoted to a first-paint cache, ADR 0014 D1).

- A locally **hidden** card stays hidden.
- A locally **visible but unentitled** card is stored `preferred_visible=true` and rendered hidden —
  so it returns automatically the moment entitlement is restored.
- **`isTrustedGesture` is preserved on every user-initiated write.** It exists because of the
  2026-08-07 zero-interaction mass-write incident (`CommandCenterV2Page.jsx:1966-1996` (guard at `:1974-1977`)) and the
  one-time migration POST is its only exemption, marker-guarded against looping. Server-side
  throttling on the layout endpoint is the second belt.
- The offsets/sizes keys migrate with the same doc. Note `resetPanelPositions` (`:2112-2120`) clears
  position only and never touches visibility — that separation is deliberate (Henry) and is preserved
  in the server doc.
- Splitting `rightPanels` (D1) invalidates its stored offsets/sizes; those four new ids fall back to
  template defaults on first load. Acceptable and one-time.

## Explicitly rejected alternatives

| # | Alternative | Verdict | Why |
|---|---|---|---|
| A1 | **Reorder the existing ladder** so workspace beats user | Rejected — breaks live behaviour | Breaks `feature.support_impersonation` (`seed_feature_flags.py:43-48`) and `PROD_ALLOWLISTED_USER_FLAGS` (`:136`), both of which require user-beats-global, and violates the locked test `test_core_feature_flags.py:19-52`. |
| A2 | **Model A — one table, one algorithm, with a `mandatory`/`recommended` enforcement bit** (R5-shaped) | Rejected — semantics; **partially adopted** | Its Pass 1 returns at the *broadest* scope holding any mandatory rule, so a platform mandatory-ON short-circuits and a workspace mandatory-OFF is never read. That is "platform overrides admin", the opposite of Henry's chain. Its team step ("first recommended rule in `rules[scope]`") is non-deterministic when a user is in two teams, and `mandatory + enabled=True` never states whether it forces *visibility*. **Preserved disagreement:** the reuse reviewer ranked A **second** (maximal reuse; the only model that pays down existing debt) while the semantics reviewer ranked it **last** (5/10). Both are right about different things, so we take A's shared-resolver extraction as a merge-blocking P0 (D7) and reject A's resolution algorithm — rather than averaging the two verdicts into a compromise that is neither. |
| A3 | **Model C — MDM/Chrome four-state alphabet** (`value` × `enforcement` across three tiers) | Rejected — operator cognition | Its own author concedes 3 tiers × 4 states = 12 cells. `forced_on` is a hard *grant*, not a hard *show*, so an admin who "forces on" and doesn't see the card on a colleague's desk files a bug — the exact user-left-confused failure this ADR exists to prevent, relocated onto the admin. R6: Apple shipped three enforcement frequencies and collapsed to one. Also gold-plated a derivable `t:{teamset_digest}` cache dimension and a phase-4 `pinned` boolean nobody asked for. |
| A4 | **Card-level entitlement rules** (each `DESK_PANELS` id is an entitled resource) | Rejected — no precedent, and it scales wrong | R10 is an empty-set finding: Grafana, Datadog and Wiz all permission the *container* and entitle the *capability*. Would put ~24 UI keys into the same global namespace as `feature.ai_kill_switch`, returned in every `/feature-flags/` payload and every `me/summary`. |
| A5 | **Store layout preference as `USER`-scoped `FeatureFlagRule` rows** | Rejected — cache blast radius + semantic inversion | Every write bumps a **global** cache version (`django_cache_feature_flag_adapter.py:25-32`); one user hiding CLOCK invalidates every tenant. And it repurposes the USER scope, which currently means operator escalation, into preference. |
| A6 | **A second, purpose-built entitlement subsystem** (own table, own resolver, own API) | Rejected — DRY + a standing decision | `components/subscription/domain/entitlements.py:11-14` already ruled it: entitlements own **numeric limits only**; *"Boolean tier features ride the existing FeatureFlag / FeatureFlagRule system… we do not build a second boolean-gating mechanism here."* Respected, not superseded. |
| A7 | **Team entitlement tier in v1** | Deferred to P4 (not rejected) | ~3–4 days for a tier no operator has asked for, and it drags in three unresolved things: `Team.members` is M2M so the resolver must intersect (never `profile.active_team_id`, which is user-switchable per ADR 0007); the two membership representations disagree (`components/membership/api/permissions.py:266` reads the M2M, `components/workspace/api/permissions.py:323-327` reads `TeamMembership`); and `Team.plan` exists (`infrastructure/persistence/team/models.py:70-72`) while `_workspace_plan_tier` deliberately refuses `PlanQueryPort.get_plan_for_workspace` because it resolves the *Team* plan — *"routing the gate through that would let the two diverge"* (`feature_flags.py:22-25`). A team tier resolving through `Team.plan` resurrects exactly that divergence. Platform → workspace → user delivers Henry's stated intent; team slots into the same intersection later with no redesign. |

### The weakness of the chosen model, stated plainly

**It cannot express forced-visible.** `visible = entitled AND preferred_visible` means an admin can
turn a capability *off* for everyone but cannot pin a card *on* — there is no way to mandate that
BRIEF stays on every desk, or that a compliance-required card cannot be hidden. The semantics
reviewer scored the model 9/10 and docked exactly this point.

We accept it for v1 on three grounds: Henry's words describe the OFF direction (*"overrides the user
turning that card on"*); A3 shows the ON direction is where operator confusion actually lives; and if
a pin is genuinely wanted it is a **separate, honest concept** (`pinned: true` on a card, evaluated
after preference) rather than a fourth state smeared across the enforcement axis. **OQ3** puts it to
Henry rather than deciding it silently.

### One live defect this design fixes, and one it does not

**Fixes:** today the plan-tier layer sits *below* user and workspace rules and is unlock-only
(`feature_flags.py:231-241`), so a `USER`-scoped rule with `enabled=True` grants a paid capability to
a workspace that never bought it. D3 puts the plan tier at T0 for `kind=capability` keys, closing it.

**Does not fix:** `kind=experiment` keys keep that ordering and therefore keep the bypass. That is
correct for what experiment flags are (nothing paid rides them today, `tier_features.py:32-35` is
empty), but it is a real edge that must be re-checked the moment a paid capability is put behind an
experiment-kind key.

## Relationship to ADR 0014 (api#230, OPEN) — clause by clause

ADR 0014 is unmerged: `docs/adr/` on main jumps 0013 → 0015, and `grep -rn "HudLayout\|hud_layout"`
returns zero Python hits — no model, no port, no flag.

| 0014 clause | Disposition |
|---|---|
| **D1** — `HudLayout` scoped to (user × workspace), backend-persisted, localStorage demoted to cache | **Extended.** Adopted verbatim; D4 pins ownership to `identity` and D10 specifies the migration. |
| **D2** — versioned JSON doc, unknown ids fall back | **Extended.** Adopted; the doc gains `preferred_visible` as a field distinct from rendered visibility (D3). |
| **D3** — precedence *user override → persona template → system default* | **SUPERSEDED as the whole story; preserved as one of two axes.** 0014's ladder is a *preference* fallback and remains exactly that (D3's `resolve_preference`). What it lacks is any entitlement tier — it cannot express "an admin turned this off for you". D3 composes it under a narrowing entitlement resolution. |
| **D4** — persona templates keyed on membership persona + team lens | **Extended and re-labelled.** They are preference *defaults*, never permissions (D9, ADR 0002). |
| **D5** — dnd-kit now, `react-grid-layout` deferred + pinned | **Extended.** Unchanged. |
| **D6** — ORM under `infrastructure/persistence/`, `HudLayoutStorePort`, CQRS read returning the *resolved* layout, persona→template as an application policy, templates as seed data, whole thing behind a flag | **Extended.** Unchanged, and D8 strengthens "resolved read" into "the frontend computes no policy at all". |
| **D7** — branding out of scope | **Extended.** Still out of scope. |
| **§1 "what already exists" table** | **Invalidated — must be corrected before 0014 merges.** It says "no show/hide"; show/hide, the `DESK_PANELS` catalog and Settings ▸ Appearance ▸ Layout all shipped after it was written (fe#151 `028050a`, #152 `9883597`, #154 `8452636`). It also predates the 2026-08-08 default widening to `['today', 'activeScans', 'codeRepos']` (`v2Constants.js:491`). |
| **§5 Q2** — do teams/admins define a shared template members inherit? | **Answered by splitting it.** Teams get an *entitlement* tier (narrowing, P4) and *optionally* a *template* tier (fallback, D9). Two different mechanisms; the question was hard because it assumed one. |

**Recommended handling:** merge 0014 with its §1 table corrected and D3 annotated "see ADR 0020",
rather than closing it. Its D1/D2/D5/D6 are the build spec for P1 of this plan.

## Consequences

**Positive.** One flag registry, one rule table, zero new permission keys, and the platform tier is a
data edit (`TIER_FEATURE_MAP`) plus an existing staff surface rather than a build. The
`preferred_visible`/`visible` split makes restrict→re-enable structurally lossless. Server-persisted
layout fixes a shipped bug (localStorage not namespaced by user or workspace) independently of the
entitlement work. Every "why is my card gone?" has a server-authored answer instead of a frontend
guess. And P1/P2 alone deliver the persona-templated layout two operators asked for.

**Negative / costs.** Two prerequisites are non-optional and neither is free: splitting `rightPanels`
(and invalidating its stored geometry), and resolving `requiresAdmin` — making it real removes PROMPT
QUALITY from non-admins who have it on today. The `kind` discriminator means two evaluation paths
must be kept honest by tests forever (mitigated, not eliminated, by the P0 extraction). The
forced-visible gap is real (above). A `CheckConstraint` change lands with the team tier and needs a
data-safe migration. And the desk payload grows `me/summary`, which is already a bootstrap hot path —
the desk read needs its own query-count regression test per `performance.md` §1.

## Non-goals

- **Not a second flag system**, and not a boolean-entitlement table (A6; `subscription/domain/entitlements.py:11-14`).
- **Not a security boundary** (D2). Data endpoints keep their independent gates.
- **Not card-level ACLs** (A4).
- **Not `react-grid-layout`** — ADR 0014 D5 stands; dnd-kit reorder/show-hide only.
- **Not branding** — ADR 0014 D7.
- **No inversion of the existing resolver** for `kind=experiment` flags, ever (D0).
- **Not a workspace-admin-editable *layout* (as opposed to *capability*) for other users** in v1 — see OQ5.

## Phased build plan (each phase awaits Henry's go; each is independently shippable, smallest first)

**P0 — Extract the shared resolver (~1 d). Merge-blocking prerequisite; zero behaviour change.**
One pure `_resolve(flag, rules_by_scope, tier)` called by both `evaluate_feature_flag` and
`flags_for_context`. Prove inert against `test_core_feature_flags.py:19-52`. Ships alone, valuable
alone (it removes a live duplication), and stops this ADR from adding a third and fourth precedence
implementation on top of two.

**P1 — Server-persisted layout, no entitlement chain at all (~8 d). The operator ask + the live bug.**
`DESK_CATALOG` in the shared kernel + FE contract test; **split `rightPanels`** into four ids;
**resolve `requiresAdmin`**; `HudLayout` model + `HudLayoutStorePort` + desk CQRS read in `identity`;
`GET .../desk/` and `PUT .../hud-layout/`; `me/summary` embeds the desk; `CommandCenterV2Page` reads
the server doc with localStorage as first-paint cache; the D10 one-time migration with
`isTrustedGesture` preserved; consolidate the seven direct `deskPanelVisible()` call sites; query-count
test on the desk read. **Fixes the not-namespaced-by-user/workspace bug on its own.**

**P2 — Persona templates (~3 d).** Seeded templates per persona × team lens; `resolve_preference`'s
template layer; "reset to template" in Settings ▸ Appearance ▸ Layout. Completes the Tom/William ask.

**P3 — The entitlement chain, platform → workspace (~6 d). Henry's hierarchy.**
`FeatureFlag.kind`; `resolve_capability` with T0 (plan map + staff GLOBAL) and T1 (workspace,
deny-only) — which closes the plan-tier bypass for capability keys; the restrict/clear write API +
`manage_settings` + audit; the desk read gains `entitled` / `entitlement_tier` / `locked`; locked-row
UI with server-authored reasons; populate `TIER_FEATURE_MAP` with the capability keys the pricing
model actually gates (OQ1). Precedence matrix tests, including an explicit "a lower tier cannot
re-grant" test and a "grant attempt is 400" test.

**P4 — Team tier (~3–4 d). Only on demand.** `Scope.TEAM` + FK + constraints + migration; intersection
over `teams_of(user, ws)`; `m2m_changed` invalidation; team capability endpoints; resolve the
`Team.members` vs `TeamMembership` inconsistency first (it is a prerequisite, not a detail).

**P5 — Admin console polish (~2 d). Optional.** Settings ▸ Workspace ▸ Capabilities showing effective
state with Inherited/Overridden labelling (R7); a staff platform-tier surface if Django admin proves
too coarse.

**Totals:** ~12 d for P0–P2 (everything operators asked for, plus a bug fix); ~18 d through P3
(Henry's stated hierarchy); ~22 d with the team tier.

## Open questions (for Henry)

1. **Does the platform tier resolve through subscription plan entitlements, or hand-set staff flags?**
   Recommendation: **both, in that order** — `TIER_FEATURE_MAP` is the pricing model (R9: derive from
   billing, never hand-set per customer), and a staff `GLOBAL` rule is the per-customer override that
   wins over it. Both mechanisms already exist and are wired end-to-end; `_PRO_FEATURES` /
   `_PREMIUM_FEATURES` are literally empty frozensets today (`tier_features.py:32-35`). The real
   question underneath is the *pricing* one: **which capabilities are Free vs Pro vs Premium?** That
   is a decision only you can make, and P3 cannot ship without it.
2. **Is the team tier in v1, or deferred?** Recommendation: **deferred to P4**, with teams getting a
   *template* tier in P2 instead. Every model and every reviewer priced it at ~3–4 days for a tier no
   operator has requested, and it drags in the `Team.members`/`TeamMembership` split and the
   `Team.plan` divergence (A7). Say the word and it moves to P3.
3. **Do you want forced-vs-default enforcement, or is deny-only enough?** Recommendation: **deny-only**
   — it makes the whole thing one sentence, and the four-state alphabet is where operators get lost
   (R6, A3). But this is the one place the chosen model is genuinely weaker: it cannot pin BRIEF on.
   If "some cards must stay visible" matters to you, say so and it becomes an explicit `pinned` flag
   on the catalog entry, not an enforcement mode.
4. **Sequencing: preference-first (P1/P2 before P3), or chain-first?** Recommendation:
   **preference-first.** The chain has one requester (you); the layout has two operators on record and
   fixes a shipped bug. Nothing is wasted either way — the desk read already returns `visible`, so the
   chain is later just one more AND. But it is your call whether the hierarchy is the point or the
   layout is.
5. **Can a workspace admin set a *layout* (not a capability) for other people?** I.e. "everyone in this
   workspace starts with these cards", separate from entitlement. This is ADR 0014 §5 Q2 restated for
   the preference axis. Recommendation: **not in v1** — a workspace-level *template* (fallback, users
   may still change it) is a small addition to `resolve_preference` in P2 if you want it; a
   workspace-level *forced* layout is question 3 again.
6. **Blast radius: should a workspace restriction also 403 the underlying API, or only remove the card?**
   Recommendation: **yes, 403** — one key, no divergence, and the endpoints already read it. But be
   clear what that means: restricting `feature.cloud_posture` for a workspace stops its cloud-posture
   scans, it does not merely tidy the desk. If you want "hide the card but keep scanning", that is a
   second UI-only key per capability and I would argue against it.
7. **Should an operator see a capability they aren't entitled to?** Recommendation: **yes — locked row
   with a reason** (R8: Slack's lock icon, Notion's "managed by your organization"); silent
   disappearance is the failure you keep calling out. The counter-argument is that advertising
   unpurchased features to a security buyer is noise. Plan-locked and admin-locked could differ (show
   the upgrade path, hide the org restriction) — your call.

[^grafana-prefs]: Grafana docs, "Organization preferences" — Server → Org → Team → User cascade; *"the lowest level always takes precedence"* (fetched 2026-08-07): https://grafana.com/docs/grafana/latest/administration/organization-preferences/
[^grafana-perms]: Grafana docs, "Manage dashboard permissions" — View/Edit/Admin ACLs on dashboards and folders, a system separate from preferences (fetched 2026-08-07): https://grafana.com/docs/grafana/latest/administration/user-management/manage-dashboard-permissions/
[^ff-vs-ent]: Featureflow, "Feature Flags vs Entitlements" — engineering-owned short-lived flags vs product/billing-owned permanent entitlements (fetched 2026-08-07): https://www.featureflow.com/blog/feature-flags-vs-entitlements
[^kaiten]: Kaiten, "Entitlements vs Feature Flags" (fetched 2026-08-07): https://kaiten.sh/blog/entitlements-vs-feature-flags
[^ld-entitlements]: LaunchDarkly, "How to manage entitlements with feature flags" (2020-01-28) — advanced use case; single upstream source of truth in billing synced into flags; incorrect-billing risk; audit logging required: https://launchdarkly.com/blog/how-to-manage-entitlements-with-feature-flags/
[^ld-targeting]: LaunchDarkly docs, "Target with flags" — off-variation → prerequisites → individual targeting → rules → default rule; individual beats segment (fetched 2026-08-07): https://launchdarkly.com/docs/home/flags/target-rules
[^flagsmith]: Flagsmith help, "Do identity overrides take precedence over segment overrides?" — *"Identity overrides always take precedence"* (fetched 2026-08-07): https://help.flagsmith.com/en/article/do-identity-overrides-take-precedence-over-segment-overrides-166jzcs/
[^statsig]: Statsig docs, "Overrides" — ID overrides return immediately, before any rule evaluation (fetched 2026-08-07): https://docs.statsig.com/feature-flags/overrides
[^unleash]: Unleash, "Feature toggles with strategy constraints" — a strategy fires iff every AND-ed constraint holds; no per-user override tier (fetched 2026-08-07): https://www.getunleash.io/blog/feature-toggle-with-strategy-constraints
[^aws-scp]: AWS Organizations docs, "SCP evaluation" — *"SCPs do not grant permissions"*; effective permissions are the intersection root → OU → account ∩ identity policy (fetched 2026-08-07): https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_evaluation.html
[^chrome]: Google Chrome Enterprise Help, "Set Chrome policies for users or browsers" — mandatory policies force the setting and cannot be changed by users; recommended policies are changeable defaults; *"a mandatory policy still overrides a recommended policy"* (fetched 2026-08-07): https://support.google.com/chrome/a/answer/9037717
[^gpp]: Microsoft Learn, "Group Policy Preferences" — Policies are enforced (UI greyed out), Preferences are deployed defaults the user may change; where both define a setting, **the policy wins** (fetched 2026-08-07): https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/group-policy/group-policy-preferences
[^mcx]: Bresink, "Managed Client (MCX) documentation" — the historical Once / Often / Always enforcement frequencies, collapsed to Always by modern configuration profiles (fetched 2026-08-07): https://www.bresink.com/osx/300268194/Docs-en/pgs/0050-MCX.html
[^gws-ou]: Google Workspace Admin Help, "How the organizational structure works" — nearest-OU-wins; a child OU may override the parent, including re-enabling a service; settings labelled Inherited / Overridden (fetched 2026-08-07): https://support.google.com/a/answer/2655363
[^slack-lock]: Slack Help Center, "Manage a workspace in an Enterprise organization" — org-locked preferences render with a lock icon (fetched 2026-08-07): https://slack.com/help/articles/115005225987-Manage-a-workspace-in-an-Enterprise-organization
[^notion-org]: Notion Help, "Organization-level controls" — settings surfaced to workspace owners as "managed by your organization" (fetched 2026-08-07): https://www.notion.com/help/organization-level-controls
[^stripe-ent]: Stripe docs, "Billing — Entitlements" — features attach to products; subscribing auto-creates the customer's `ActiveEntitlement`; read entitlements or subscribe to the summary event (fetched 2026-08-07): https://docs.stripe.com/billing/entitlements
[^dd-rbac]: Datadog docs, "Role Based Access Control" — dashboards restricted via `restricted_roles` (fetched 2026-08-07): https://docs.datadoghq.com/account_management/rbac/
[^dd-restrict]: Datadog API docs, "Restriction Policies" — `editor`/`viewer` relations mapped to principals; per-dashboard *view* restriction available on request / paid plan (fetched 2026-08-07): https://docs.datadoghq.com/api/latest/restriction-policies/
[^wiz-roles]: Stitchflow, "Wiz user management guide" — Global Admin/Reader, Project Member/Admin, custom roles on Enterprise; scoping is role × project/tenant, never per widget (fetched 2026-08-07): https://www.stitchflow.com/user-management/wiz/manual
