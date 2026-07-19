# Auto-Sec — Persona / Role / Layout Model (design SSOT)

**Status:** approved model, taxonomy pending final confirmation · **Date:** 2026-07-17
**Decision owner:** Henry · **Author:** Claude

This is the single source of truth for how a member's identity in an Auto-Sec
organization maps to (a) the **dashboard layout** they see and (b) the
**permissions** they hold — including which AI agents they can run and what those
agents may do. It consolidates three research threads (security-team taxonomy,
scalable authorization + adaptive dashboards, AI-agent-as-principal governance)
into an implementable design.

---

## 1. Problem

The single-screen HUD command center shows everything at once — overwhelming for
a new operator, and wrong for the fact that a red-team pentester and a blue-team
SOC analyst want different default surfaces. We also can't answer "who can run
which agent, and what is that agent allowed to do" until we've decided what a
member *is*. And we will add more personas over time, so the model must be cheap
to extend — **adding a persona must be data, not a code change**.

## 2. Locked decisions (confirmed with Henry, 2026-07-17)

1. **Two orthogonal axes**, not one bundled "security persona":
   - **Posture** (discipline) → drives **layout**. red / blue / purple / infra-SRE / devsecops / admin.
   - **Role** → drives **permissions** (enforced RBAC), incl. agent access.
   This is the proven `persona ≠ role` split (ADR-0002 in the parent platform):
   permission reads **role only, never posture**.
2. **AI Agent is its own capped principal**, not a user role — it acts under a
   *delegated* authority that can never exceed the human who dispatched it.
3. **Layout = customizable default**: posture sets the starting card set/menu;
   the user can drag/hide/save their own arrangement.

## 3. The load-bearing scalability rule

> **Never let enforcement or UI reference a posture/role by name.** Check
> *capabilities*, resolve *layout profiles*. Then a new persona = insert rows.

Research consensus (NIST, Evolveum, Permit.io, Oso, WorkOS): a role *enum* is the
cheapest thing to start with and the most expensive thing to grow — because
role-name checks scatter across the app as `O(roles × call-sites)`. Two
indirections remove that cost permanently:

- **Role → capability set.** Code asks `can("agent:run")`, never `role == "operator"`.
  A role is a named bundle of capabilities. New role = one row listing its caps.
  Zero enforcement changes. (This is exactly Django's `user.has_perm("app.codename")`
  contract — the call site is agnostic to how the user got the permission.)
- **Posture → layout profile.** The HUD reads "which layout profile does this
  posture map to?" — a list of default cards + menu order (data). New posture =
  one profile row. Zero UI forks. (This is the parent's `visible_sections`
  mechanism generalized.)

Therefore **postures and roles are rows in a table**, seeded with system defaults +
per-workspace custom rows — admin-definable, not code enums.

## 4. Taxonomy (seeded defaults — extensible)

Because postures/roles are data, this starter set is not a lock-in; new entries
are added anytime without code.

### 4.1 Postures (→ layout) — a *switchable* lens, not an identity lock
People span postures (purple teamers; T3 analysts who hunt *and* write detections;
a SOC manager who is "blue" but oversees red results). A member has a **default**
posture and can flip the lens freely.

| Posture | Default HUD surfaces |
|---|---|
| 🔴 Red (offense / pentest) | Recon · Enumeration · Targets/attack-surface · Exploit-suggest · Findings |
| 🔵 Blue (defense / SOC) | Alerts · Triage board · Detections · Threat Hunt · Log Intel |
| 🟣 Purple | Red + Blue, correlated (attack ↔ detection coverage) |
| 🟢 Infra / SRE | Asset inventory · Reliability signals · Config/posture drift · Incidents |
| 🟠 DevSecOps | Pipeline/scan findings · Vuln backlog · Policy-as-code · SBOM |
| ⚙️ Admin / Org | Members · Roles · Audit log · Agent governance · Integrations |

### 4.2 Roles (→ permissions, enforced)

| Role | Holds (capability bundle) |
|---|---|
| Owner | Everything + billing + delete org |
| Admin | Members, roles, integrations, agent governance, audit |
| Operator | Run + configure agents, approve medium-risk actions |
| Analyst | Run read/triage agents, work the board, no risky actions |
| Viewer | Read-only |

Industry corroboration: this reader→responder/analyst→contributor/admin ladder is
what every surveyed product ships (MS Sentinel, CrowdStrike, SentinelOne, Panther,
Wiz, Elastic). Elastic even names roles after job functions (Tier-1/2/3 analyst,
rule author, SOC manager) — validating role-as-job-function naming when useful.

> **Novelty note:** posture-drives-layout is a genuine product innovation — no
> surveyed SIEM ships red/blue/purple as a first-class UI axis. Valuable *as long
> as* posture stays a switchable layout lens and never touches permission.

## 5. Permission catalog (`resource:action`)

Name permissions by action-on-resource, hierarchically namespaced, never baking a
role name in (`admin_delete` is an anti-pattern). Examples:

```
alerts.read        alerts.triage       incidents.contain
agents.run         agents.configure    agents.approve_highrisk
recon.run          exploit.execute     detections.author
members.manage     roles.manage        audit.read
integrations.manage
```

Roles are grant-only bundles of these. Sensitive caps (e.g. `exploit.execute`) are
**never-assignable** to tenant-authored custom roles (Frontegg Never/Assignable/Always
model); custom roles may only *narrow* a template, never escalate (Cerbos).

## 6. Layout architecture (per-posture default + user customization)

Dashboards are **data, not a React component per persona**:

- Each dashboard = a **versioned JSON layout** (`{i,x,y,w,h}[]`, react-grid-layout
  shape) + a `{widgetType → component}` **widget registry**. "Config says what to
  show; components know how to show it."
- **Effective layout** resolves by precedence (Grafana's proven chain, user wins):
  `user_override ?? posture_default ?? org_default ?? system_default`.
- User drags/resizes → debounced `onLayoutChange` → per-user override row.
- **Version every layout** (`schema_version` + a load-time migrator) so saved
  user dashboards survive schema changes; deprecate widget types, never hard-delete
  one a saved layout references.
- **Widgets are RBAC-gated at render** — a config row must not grant data access.
  The renderer filters the widget list by the viewer's capabilities *before*
  render, and each widget's query is independently authorized. This is where §5
  (role) and §6 (posture) meet: **posture picks the default layout; role/caps
  decide which widgets actually render and with what data.**

Adding a persona = insert a Role row + a posture-default-layout row → **zero code,
zero forks.**

## 7. AI agent = capped, delegated principal

Model an agent as its own **`AgentPrincipal` (a governed non-human identity)**,
distinct from `User`. Never a user role.

- **Delegation, not impersonation.** Each dispatch mints a short-lived,
  audience-scoped credential via OAuth Token-Exchange / on-behalf-of (RFC 8693)
  carrying *both* identities (dispatcher + agent). Effective permission =
  `intersect(agent.grantedCaps, dispatcher.liveEntitlements)`, re-narrowed at every
  downstream hop. An agent can never out-permission its human. (OWASP ASI03
  Identity/Privilege Abuse is the failure mode this defeats.)
- **Risk tiers via a DETERMINISTIC classifier (never an LLM).** For a product
  ingesting attacker-controlled data, an LLM classifier can be prompt-injected into
  rubber-stamping. Rules decide the tier; the LLM is at most an input the rules
  re-check. (AWS Well-Architected Agentic Lens, AGENTSEC04-BP02.)
  - read/recon → autonomous
  - low-risk writes (annotations, tickets) → single reviewer
  - irreversible → multi-reviewer / out-of-band, **propose → approve → execute**,
    timeout **defaults to block**.
- **Offensive actions carry a hard human-gate FLOOR** independent of the delegated
  cap. `exploit.execute` / containment / teardown are capability-*ineligible* for
  autonomous execution **even if** the dispatcher could do them manually — the cap
  sets the ceiling, a separate offensive-action policy sets a floor that always
  requires `sign_off`. Plus a deterministic in-scope target pre-check the agent
  cannot widen. (Governed-autonomy consensus for offensive automation.)
- **Every action → a tamper-evident, signed audit record** binding *who
  authorized*, *agent identity + version*, *reasoning summary*, *the policy checks
  that fired*, *reviewer decision + timestamp*, result. (NIST accountability /
  non-repudiation; EU AI Act Art. 12.)

## 8. Reuse — this is mostly repurposing, not new scaffolding

The fork already carries the bones (verified 2026-07-17):

| Need | Already in the fork |
|---|---|
| Role field (RBAC) | `WorkspaceMembership.role` (`Role`: owner/admin/member) |
| Posture field (layout lens) | `WorkspaceMembership.persona` (`Persona` enum — repurpose values) |
| Role policy | `components/identity/domain/policies/workspace_role_policy.py` + `components/membership/*` |
| Approval gate | `components/sign_off` |
| Audit trail | `components/audit` |
| Agent framework | `components/agents` (`@register_agent`, `@requires_role` → evolve to `@requires_capability`) |

We repurpose enum *values* and add the capability + layout-profile + AgentPrincipal
layers on top. We do **not** rebuild membership/RBAC/audit/sign-off.

## 9. Migration path (enum → seeded rows + custom rows)

Expand/contract, each phase its own deploy (no downtime):
1. Seed a `Role` table + `Permission` catalog + `role_permissions` from current enum
   values (system rows, `is_system=True`, undeletable). Data migration via
   `apps.get_model()` + `get_or_create`.
2. Add nullable `role_id` FK on membership; dual-write + backfill in batches.
3. Migrate enforcement from `@requires_role("admin")` → `@requires_capability("members.manage")`.
4. Seed posture rows + one default-layout row per posture.
5. Drop the enum columns last.

Start **in-process** (Django Groups/Permissions or Casbin — DB-backed, per-tenant,
no sidecar). Graduate to **OpenFGA** only if authorization becomes fundamentally
relationship-shaped (workspace→team→asset→alert containment). Avoid Oso (OSS
deprecated Dec 2023); Cedar/OPA are heavier than needed now.

## 10. Phased build

- **P1 — Capability foundation.** `Permission` catalog + `Role`/`role_permissions`
  rows (system + custom), `@requires_capability`, migrate existing checks. Ship
  behind a flag; no UX change yet.
- **P2 — Posture + layout profiles.** Posture rows, per-posture default layout
  (JSON) + widget registry, effective-layout resolver, per-user overrides + save,
  RBAC-gate widgets at render. HUD reads its default from posture.
- **P3 — AgentPrincipal.** Agent identity object, delegated token-exchange
  (intersect caps), deterministic risk classifier + tier gate wired to `sign_off`,
  offensive hard-floor policy, signed audit records.
- **P4 — Admin surfaces.** Manage members/roles/postures, assign default layouts,
  agent governance (which agents a role/posture can run), audit viewer.

## 11. Open decisions

- Final posture + role taxonomy (starter set above — confirm/adjust).
- Whether posture is a new field or a rename of `persona` (leaning: reuse `persona`
  mechanism, new values).
- Workspace switcher (private space ↔ team spaces) — the org-container UX that
  surfaces the current org label top-left and lets a member switch. This is the
  same org model; specced here, implemented in P4 (frontend top-left switcher +
  `/me/summary` workspace list).

## References

- OWASP GenAI — Top 10 for Agentic Applications 2026 (ASI03 Identity/Privilege Abuse)
- CSA — Agentic AI IAM approach; NHI governance (least-privilege, ephemeral creds)
- AWS Well-Architected — Agentic AI Lens, AGENTSEC04-BP02 (risk tiers, HITL); Cedar least-privilege across agent chains
- Microsoft Entra Agent ID (agent-as-first-class-identity)
- RFC 8693 OAuth Token Exchange (on-behalf-of delegation); NIST agent-identity concept work
- NIST/Kuhn RBAC-A; Evolveum role-explosion; WorkOS multi-tenant RBAC; Grafana precedence/provisioning; react-grid-layout; Perses schema versioning
- Red/blue/purple: TechTarget, Pluralsight, Picus, Wiz · SOC tiers: q-sec, Palo Alto, Prophet (tier flattening)
- Product RBAC models: MS Sentinel, CrowdStrike Falcon, SentinelOne, Panther, Wiz, Elastic Security, Splunk ES
</content>
