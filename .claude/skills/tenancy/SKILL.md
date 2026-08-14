---
name: tenancy
upstream: none
description: >
  Use when working on multi-tenancy in autosec — tenant identification (subdomain / host),
  the tenant registry, the database router, tenant-scoped managers, PostgreSQL row-level
  security, per-tenant database provisioning, Celery tenant binding, webhook tenant
  resolution, or ANY change that touches DATABASES, DATABASE_ROUTERS, middleware ordering,
  or a queryset over workspace-scoped data. Carries autosec's two-tier decision (pooled vs
  dedicated), the traps that have already bitten this codebase, and the invariants that must
  never regress. Invoke BEFORE writing tenancy code, not after.
why: |
  autosec inherited a broken host→database router from the wanjala fork and spent real time
  reasoning from it. This skill exists so the next person (or agent) starts from what is
  actually true, and knows which of the inherited pieces are load-bearing.
---

# Tenancy — how autosec separates customers

**Read this before touching `DATABASES`, `DATABASE_ROUTERS`, middleware, or any queryset over
workspace-scoped data.**

Authoritative decisions live in `docs/adr/0028-tenancy-shared-schema-with-rls.md` and
`docs/adr/0029-*.md`. This skill is the working knowledge around them: the three models, the two
tiers autosec actually ships, and — most importantly — the specific traps this codebase has
already fallen into.

For connection **pooling** (PgBouncer, psycopg3) see the kit's `sql` skill. Pooling and tenancy
interact badly in one specific way; §7 covers it.

---

## 1. The three models (vocabulary)

| model | shape | isolation | cost |
|---|---|---|---|
| **Pool** — shared DB, shared schema | one database, `tenant_id`/`workspace_id` column, every query filters | application code only | lowest |
| **Bridge** — shared DB, schema per tenant | one database, N PostgreSQL schemas, `search_path` switching (`django-tenants`) | schema boundary | migrations run per schema |
| **Silo** — database per tenant | N databases, router picks by tenant | connection boundary | provisioning, migrations, pooling per tenant |

Industry terms (AWS SaaS lens uses pool/bridge/silo); most Django articles say "shared schema /
separate schemas / separate databases".

## 2. What autosec ships: three tiers, one abstraction (two built)

| tier | who | shape | status |
|---|---|---|---|
| **T1 Pooled** (default) | everyone — trials, SMB, "just want to try it" | shared DB on `app.auto-sec.ai`, scoped by `workspace_id`, RLS backstop | build |
| **T2 Dedicated** | named compliance requirement, or pays for it | own database on our infra, routed by subdomain | build |
| **T3 BYOC / self-host** | customer runs the database (or the stack) in their own cloud | control plane ours, data plane theirs | **deferred — see §2c** |

Both built tiers run on **one codebase**. The registry row says which mode; the abstraction hides
the difference from application code: *the interface stays the same, only the implementation
changes.*

### 2a. Pooled is the permanent home of almost everyone — not a compromise

Industry data (2026): pooled + Postgres RLS **handles the first 500–1,000 tenants with no
architectural change**, and selective migration to a dedicated database happens for only **1–5% of
tenants** — a typical hybrid runs 5–15 dedicated instances against a pooled majority. Signing up,
creating a workspace and poking around must never trigger provisioning.

Name the shared console **`app.`**, not `development.` — an environment word in a tier position
reads as staging and invites "is my data real?".

### 2b. The sales trigger for T2 is a compliance name, not a vibe

Pool satisfies **SOC 2 and GDPR**. Silo is what's required for **HIPAA BAA, PCI Level 1, and
sovereign data residency**. When a prospect says "we want isolation", ask which of those they are
being audited against. If the answer is none, pooled + RLS is the honest sell and the cheaper one.

### 2c. T3 (BYOC) is deferred deliberately — the cost is the support model, not the code

Scott (2026-08-13) asked what happens if a customer wants to host their own database. That is BYOC,
and it is a different cost structure from T2, not a bigger version of it:

- *"The hard part of BYOC isn't the first deploy. It's the N environments that all look different."*
- Debugging happens across a trust boundary you do not control — operational changes can require a
  call with the customer to make a change or diagnose an outage.
- Version drift stops being technical and becomes per-customer policy.
- Every change needs rollout windows and remote observability **from day one**.

For a small team that is the expensive tier. **Sell T2 first; build T3 when a signed contract
requires it, priced for the support model.**

**The honesty test for T3**, worth knowing before anyone puts "BYOC" on a slide: *can the vendor
see the payload of a request?* If our control plane terminates traffic and forwards it, that is not
BYOC — it is SaaS with a private connection. Do not call it BYOC in that case.

### 2d. HARD INVARIANT — `default` is a control plane and holds NO customer data

BYOC's defining structure is control-plane / data-plane separation: the vendor runs UI, API,
orchestration and observability and **holds no customer data**; the customer's environment holds
the data.

The T2 design already has that shape — registry in `default`, tenant data in the tenant database.
Which means **T3 stays reachable as a connection-string source plus an ops model rather than a
rewrite, for exactly as long as we keep `default` free of customer data.** The moment something
tenant-owned is put in `default` "for convenience" (a cross-tenant search index, a shared audit
table, a reporting rollup), T3 is foreclosed and the only way back is a data migration out of the
control plane.

Treat any proposal to put customer data in `default` as a decision to abandon T3, and say so.

**"No customer data" ≠ "no data".** The opposite misreading is just as costly. `default` is the
right home for **global reference data** — public facts owned by nobody:

| goes in `default` (shared reference) | goes in the tenant DB (customer-owned) |
|---|---|
| `vuln_intel` — EPSS scores, CISA KEV catalog (~280k rows, identical for everyone) | findings, scans, assets, workspaces, users, tasks, audit |
| subscription tier / plan definitions | a tenant's subscription state |
| feature-flag definitions | a tenant's flag overrides |
| the tenant registry itself | — |

Replicating the EPSS feed into every tenant database because "no data in `default`" would be
absurd: it is public, identical, and 280k rows per tenant.

**The pattern that makes this work is joining reference data BY VALUE, not by FK.** Verified
2026-08-14: nothing workspace-scoped has a `ForeignKey` into `vuln_intel`; the read path is
`EpssScoreModel.objects.filter(snapshot_id=…, cve=cve)` — a lookup on the CVE string. That survives
a database split unchanged. **A `ForeignKey` from tenant data into shared reference data would not**
— Django cannot span databases, so it would either pin that table into every tenant DB or block the
split entirely. Keep reference joins on natural keys.

### 2e. Bridge (schema-per-tenant) is still not offered

It costs a migration run per schema per deploy and satisfies neither ask: an evaluator does not care
about schema boundaries, and a customer demanding physical separation is not satisfied by a schema
inside a shared database. Add it only when a named customer requires exactly that middle ground.

## 3. The traps — these have already bitten this codebase

### 3a. `threading.local` is WRONG here — autosec is ASGI

Nearly every multi-tenancy article stores the current tenant in `threading.local()`. autosec runs
**daphne + channels** (`ASGI_APPLICATION = "api.asgi.application"`). Under ASGI a single thread
serves many concurrent requests through the event loop, so a thread-local tenant is not merely
stale — **request A's tenant is visible to request B on the same thread.**

Use `contextvars.ContextVar`. It is scoped to the async task, which is the correct granularity, and
behaves correctly under sync/WSGI too.

The inherited `TenantMiddleware` used `threading.local`. That is the single most dangerous line of
the inherited design.

### 3b. Falling back to `default` is the bug, not the fallback

```python
# WRONG — the shape in the inherited code and in most blog posts
def db_for_read(self, model, **hints):
    tenant = get_current_tenant()
    if tenant:
        return f"tenant_{tenant.id}"
    return "default"            # ← silent cross-tenant read/write
```

Any path that forgets to bind a tenant — a Celery task, a management command, a signal firing
outside a request, a shell — then reads and writes real data **successfully and silently** while
believing it is scoped.

**Absence of a tenant must never resolve to a database.** For a tenant-scoped model with nothing
bound, raise. Shared models route to `default` explicitly by app label. Code that legitimately runs
without a request binds a tenant deliberately.

The same rule applies to the scoped manager: `if tenant is not None: qs = qs.filter(...)` fails
open in exactly the same way.

### 3c. Django has no cross-database foreign key

This constrains the dedicated tier absolutely. `CustomUser` is the target of FKs from `Workspace`,
`WorkspaceMembership`, `Finding`, `Task`, `EntityAuditLog` and dozens more. You cannot put users in
`default` and workspaces in a tenant database.

So in dedicated mode **users live in the tenant's database**, and a dedicated-tenant account
belongs to that tenant only. Verified 2026-08-14: **0 users currently span more than one
workspace** (14 memberships), so adopting this costs nothing today — but it makes pooled →
dedicated a *migration with an identity step*, never a config flip. Do not promise otherwise.

If cross-tenant identity is ever required it is an identity-provider problem (a shared IdP both
tenants trust), not a routing problem. Do not "solve" it by moving `CustomUser` back to `default`.

### 3d. Webhooks have no subdomain — this is why the account→alias lookup exists

Stripe POSTs to one fixed URL. There is no tenant host to route on. `resolve_db_alias_for_stripe_account()`
scans configured aliases for the connected account and returns the owner.

**This function looks dead under a single database and is not.** It was very nearly deleted as
fork-drift on 2026-08-14; `components/payments/tests/integration/test_stripe_webhook_connect_routing.py`
exists specifically to assert it. The same shape is needed for any inbound integration callback
(GitHub, Slack). Bind the tenant from the payload, then proceed normally.

### 3e. Documentation that asserts a topology we don't have

On 2026-08-13 `.claude/rules/django-conventions.md` still claimed "4 PostgreSQL databases routed by
`tenants.router.TenantRouter`" — fork-drift from the nonprofit source, months stale, in an
authoritative-looking rules file. It produced a genuine false belief about tenant isolation moments
before that claim would have been made to a prospective customer.

**Never restate the tenancy architecture from memory or from a doc. Check `api/settings/`.**

### 3f. `infrastructure/<name>/` is unusable when `infrastructure/persistence/<name>/` exists

`infrastructure/__init__.py` installs an `_AliasFinder` at `sys.meta_path[0]`
(fork-inherited backward compatibility) that rewrites `infrastructure.<ctx>.*` →
`infrastructure.persistence.<ctx>.*` whenever the file exists under
`persistence/`. It wins over the real filesystem package.

So creating BOTH `infrastructure/tenancy/` (runtime) and
`infrastructure/persistence/tenancy/` (models) makes the first one permanently
unimportable — `import infrastructure.tenancy.context` resolves into the
persistence package and raises `ModuleNotFoundError`. The files are there; the
import system routes past them.

Hit on 2026-08-14 while building Phase 0. The runtime therefore lives in
`components/shared_platform/infrastructure/tenancy/`, which is also where the
inherited middleware and router lived — same concern, established home, and out
of the shim's reach.

## 4. Invariants (do not regress)

1. Tenant context is a `ContextVar`, set by middleware, cleared in a `finally`.
2. The router **raises** for tenant-scoped models with no tenant bound.
3. The scoped manager filters by default; the escape hatch is named `unscoped` so crossing the
   boundary is visible at the call site.
4. Tenant is assigned on save from context — never from client input. A request body specifying a
   different tenant/workspace must be ignored or rejected (mass-assignment protection).
5. Unknown or inactive subdomain → **404**, never a fall-through to the default console.
6. Reserved subdomains (`app`, `www`, `api`, `admin`, `auth`, `static`, …) can never be claimed.
7. Celery tasks carry the tenant explicitly in headers and bind it before the body runs.
8. Every workspace-scoped read seam ships an isolation test (§6).
9. **`default` holds no customer data** (§2d). Adding customer-owned rows to the control plane is
   a decision to abandon the BYOC tier; it must be made deliberately, not incidentally.

## 5. Where things live

| concern | location |
|---|---|
| Tenant registry (control plane) | `infrastructure/persistence/tenancy/` — the ONLY tenant table in `default` |
| Context var / bind helpers | `components/shared_platform/infrastructure/tenancy/context.py` |
| Router | `components/shared_platform/infrastructure/tenancy/router.py` |
| Subdomain middleware | `components/shared_platform/infrastructure/tenancy/middleware.py` |
| Alias resolution for a model | `components/shared_kernel/infrastructure/adapters/django_db_routing.py` (`db_alias_for_write` — Django's own router API; returns `default` when no routers are registered) |
| Transaction + lock alias agreement | `components/shared_kernel/application/transactional.py` |
| Stripe account → alias | `components/payments/infrastructure/adapters/payment_utils.py` |

## 6. Testing tenancy (the tests that matter most)

A single failure here is a potential data breach. The matrix:

```python
def test_queryset_returns_only_current_tenant()      # manager scopes
def test_api_returns_only_own_data()                 # endpoint scopes
def test_other_tenant_object_is_404_not_403()        # don't reveal existence
def test_cannot_create_into_another_tenant()         # body-specified tenant ignored
def test_unbound_tenant_RAISES_not_defaults()        # §3b — the fail-closed proof
def test_celery_task_without_tenant_fails_loudly()   # §3d
def test_unknown_subdomain_404s()                    # invariant 5
```

Existing coverage: `components/*/tests/**/test_*isolation*` and the #122 cross-tenant assertions.

**Prove the denial before trusting the mechanism** (ADR 0028 D4). For RLS specifically, the first
artifact is a test that watches a policy DENY, executed as the real non-superuser application role
— not as the owner, and not as a superuser.

## 7. RLS — the two showstoppers (pooled tier)

Before any RLS policy can be trusted:

1. **The app's DB role must not bypass RLS.** `rolsuper` and `rolbypassrls` both ignore every
   policy, and so does the **table owner** unless `FORCE ROW LEVEL SECURITY` is set. Verified
   2026-08-13: the current role has `rolsuper: True, rolbypassrls: True` — every policy would be
   ignored. Fix the role first, or the policies are decoration.
2. **PgBouncer transaction pooling breaks session-scoped `SET`.** A `SET app.current_tenant_id`
   outside a transaction can leak to the next client on that server connection. Use `SET LOCAL`
   inside an explicit transaction. See the kit `sql` skill §2a for our pooler config.

## 8. Operating the dedicated tier

- Provisioning: create the database, add the connection string, insert the registry row, run
  `migrate --database=<alias>`. It is an operational action, not self-serve signup.
- Migrations run **once per alias, every deploy**. This is the standing cost and it is linear in
  tenant count.
- `allow_migrate` must send the registry app to `default` and tenant apps to tenant aliases only,
  or you get the registry duplicated into every tenant database.
- Connection pools multiply per alias. Revisit `CONN_MAX_AGE` and pool sizing before N is large.
- Cross-tenant reporting requires explicit fan-out; there is no single query across tenants.

## 9. Local testing with subdomains

```
# /etc/hosts
127.0.0.1  app.auto-sec.ai
127.0.0.1  senso.auto-sec.ai
```

`ALLOWED_HOSTS` needs the wildcard form (`.auto-sec.ai` — leading dot matches subdomains), and the
ingress must accept both hosts. Verify with a real request per host and assert the two see
different data — a passing unit test is not proof the host actually routed.

## 10. References

- `docs/adr/0028-tenancy-shared-schema-with-rls.md` — the tenancy model, the showstoppers, and why
  "run my own tenant" is a dedicated deployment.
- `docs/adr/0029-*.md` — the two-tier decision.
- `.claude/rules/django-conventions.md` § *Tenancy* — single-DB statement + the fork-drift warning.
- `.claude/rules/persistence-and-orm.md`, `.claude/rules/performance.md`.
- kit `sql` skill — PgBouncer topology, transaction-mode caveats, indexing (composite
  `(workspace, …)` indexes are load-bearing for scoped queries).
- [testdriven.io — Django multi-tenant](https://testdriven.io/blog/django-multi-tenant/),
  [django-tenants](https://django-tenants.readthedocs.io/) (for the bridge model we chose not to
  ship), PostgreSQL RLS docs.

**Tier research (2026-08-14)** — the numbers and the BYOC cost picture in §2:

- [Multi-Tenant SaaS Architecture Patterns 2026](https://zanisssoftwares.com/blog/multi-tenant-saas-architecture-patterns-2026)
  — hybrid pooled+silo is the default pattern for SaaS selling to both SMB and enterprise; the
  compliance split (SOC 2/GDPR vs HIPAA/PCI/residency).
- [A Practical Guide for SaaS Founders in 2026](https://www.adeptdev.io/blogs/multi-tenant-architecture-a-practical-guide-for-saas-founders-in-2026)
  — pooled + RLS to 500–1,000 tenants; 1–5% selective migration to silo.
- [Estuary — BYOC redefining enterprise](https://estuary.dev/blog/byoc-redefining-enterprise) —
  control-plane / data-plane separation, the structure §2d protects.
- [Tensor9 — BYOC isn't "SaaS Anywhere"](https://www.tensor9.com/resources/byoc-playbook/) — the
  "can the vendor see the payload?" test.
- [Nuon — chaos in customer environments](https://nuon.co/blog/chaos-in-customer-envs) and
  [how to build a BYOC offering](https://nuon.co/blog/how-to-build-a-byoc-offering/) — N-environment
  drift, debugging across a trust boundary, why the cost is operational.
