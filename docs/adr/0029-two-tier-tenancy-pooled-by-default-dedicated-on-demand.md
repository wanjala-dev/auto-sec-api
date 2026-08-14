# ADR 0029 — Two-tier tenancy: pooled by default, dedicated database on demand

- **Status:** Accepted (2026-08-14)
- **Amends:** ADR 0028. Its D1 (don't port the inherited router) stands *as written about that
  implementation* but no longer implies "never route" — see D2 below. Its D3 (the two RLS
  showstoppers) and D4 (prove the denial) survive unchanged and now apply to the pooled tier.
- **Decision by:** Henry.
- **Working knowledge:** `.claude/skills/tenancy/SKILL.md`.

## Context

Two customer shapes exist and both must be served by **one codebase**:

1. *"Some people just want to try it out"* — cheap, shared infrastructure, no per-customer
   provisioning.
2. *"We don't want our data mixed with anyone else's"* — a dedicated database, or self-hosting.

ADR 0028 chose shared-schema-plus-RLS for everyone and explicitly declined to route by tenant. That
was the right call about the **inherited implementation** — a `threading.local` mapping hostnames to
database aliases that no longer existed — and the wrong call to generalise into "autosec does not
route". The approach is standard; the inherited code was broken. This ADR keeps the approach and
fixes the implementation.

## Decision

### D1 — Two tiers, not three. Bridge is deliberately not offered.

| tier | shape | for |
|---|---|---|
| **Pooled** (default) | shared database, shared schema, scoped by `workspace_id`, RLS as the backstop | trials, SMB |
| **Dedicated** | own database, routed by subdomain | pays for it, or self-hosts |

Schema-per-tenant (`django-tenants`) is **not** implemented. It costs a migration run per schema on
every deploy and satisfies neither ask: an evaluator does not care about schema boundaries, and a
customer demanding physical separation is not satisfied by a schema inside a shared database. Add it
only when a named customer requires exactly that middle ground.

### D2 — The host identifies the tenant; the registry decides what that means

```
Host: senso.auto-sec.ai → subdomain "senso" → Tenant(subdomain="senso")
        ├─ isolation_mode = "dedicated" → connection = tenant's db_alias
        └─ isolation_mode = "pooled"    → connection = default, scoped by workspace
```

`app` is the shared console and is reserved: it binds no dedicated tenant. Unknown or inactive
subdomain → **404**, never a fall-through to `app`.

### D3 — One abstraction, both tiers

Application code never asks which tier it is in. A tenant-scoped manager filters by default; the
router selects the connection. In pooled mode the filter does the work and the router returns
`default`; in dedicated mode the router does the work and the filter is a harmless no-op (that
database holds one tenant). Same interface, different implementation — which is what makes a
customer's pooled → dedicated upgrade a migration rather than a rewrite.

### D4 — Fail closed, everywhere

Neither the router nor the manager may treat "no tenant bound" as `default`. Both raise. A Celery
task, management command, signal or shell that has not bound a tenant must fail loudly rather than
silently operate on the control plane or on the wrong customer.

This is the defect that made the inherited design unsafe, and it is not fixed by the router alone —
it is fixed at every binding boundary.

### D5 — `ContextVar`, never `threading.local`

autosec is ASGI (daphne + channels). A thread serves many concurrent requests via the event loop,
so a thread-local tenant leaks *between in-flight requests*. `contextvars.ContextVar` is scoped to
the async task. Non-negotiable.

### D6 — In dedicated mode, a user belongs to one tenant

Django has no cross-database foreign key, and `CustomUser` is the FK target of most of the schema.
So users live in the tenant database. Measured 2026-08-14: **0 users span more than one workspace**
(14 memberships), so this costs nothing today. It does mean pooled → dedicated carries an identity
migration step, and that cross-tenant SSO, if ever needed, is an identity-provider problem — not
something to fix by moving `CustomUser` back to `default`.

### D7 — Webhooks resolve the tenant from the payload

Stripe POSTs to a fixed URL with no subdomain. `resolve_db_alias_for_stripe_account()` finds the
owning alias. This is load-bearing under dedicated mode and only *looks* redundant while a single
alias is configured — it was nearly deleted as dead code on 2026-08-14.

## Sequence

- **Phase 0** — registry, subdomain middleware, `ContextVar`, fail-closed router. Both tiers
  resolve; `app.` and `senso.` work locally via `/etc/hosts`.
- **Phase 1** — tenant-scoped manager + assign-on-save. Eliminates the forgotten-filter class.
- **Phase 2** — RLS on the pooled database (ADR 0028 D3 showstoppers first: non-superuser role,
  `FORCE ROW LEVEL SECURITY`).
- **Phase 3** — dedicated tier: per-alias settings, `migrate --database=` per tenant, Celery tenant
  binding, webhook resolution, provisioning runbook.

## Consequences

Migrations run once per dedicated alias per deploy. Connection pools multiply per alias. Tenant
provisioning is an operational action. Cross-tenant reporting needs explicit fan-out. A dedicated
tenant's users cannot span tenants.

In exchange: for dedicated customers, isolation is enforced by the connection rather than by
remembering a `WHERE` clause — a missing filter cannot leak across tenants because the other
tenant's rows are not in the database being queried. For pooled customers, RLS provides the
database-level backstop ADR 0028 already specified.
