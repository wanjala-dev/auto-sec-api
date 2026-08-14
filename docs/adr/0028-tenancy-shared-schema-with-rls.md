# ADR 0028 — Tenancy: shared schema, RLS-enforced, dedicated deployment for enterprise

Status: accepted
Date: 2026-08-13

## Context

A prospective customer — a security leader running infrastructure security at a startup, mid-SOC-2 —
asked the question that gates the sale:

> *"How would it exist if I was company ABC and I didn't want to trust the way that you say you
> separate data from one tenant to another? Can I run my own tenant?"*

He is sending written questions. Isolation will be on the list. So the answer has to be true.

### What is actually true today (verified 2026-08-13)

**Single database, single schema, application-enforced isolation.** `DATABASE_ROUTERS = []` in both
`api/settings/base.py:240` and `test.py:104`; one `DATABASES` alias; `tenants/router.py` exists only
in stale nested worktrees. Every tenant boundary is a `workspace_id` filter in Python.

Two known weaknesses in that posture: a `Tag` model with no workspace FK whose endpoint lists every
tenant's tags (task #83), and roughly ten workspace views on an over-permissive class that have never
been audited (#133).

### The stale rule that nearly produced a false claim

`.claude/rules/django-conventions.md` asserted *"4 PostgreSQL databases routed by
`tenants.router.TenantRouter`"* — fork-drift from the nonprofit codebase, contradicting CLAUDE.md,
sitting in an authoritative-looking rules file. It caused a real belief that we had database-level
isolation, moments before that belief would have been stated to a customer. Corrected in the same
change as this ADR.

## Decision

### D1 — Stay shared-schema. Do NOT port the old tenant router.

The wanjala `TenantRouter` resolved the database from a **thread-local** set by request middleware.
Autosec is Celery-dominant: scans, agent deep runs, log ingest and draft-PR opening all run with **no
request**. `get_current_db_name()` would return `None` and Django would fall through to `default` —
real tenant data written to the wrong place, silently. It also breaks on the async/Channels path and
returns `allow_relation: True` unconditionally.

**It fails OPEN.** That is disqualifying for a security product.

### D2 — Enforce isolation in PostgreSQL with Row-Level Security.

RLS **fails CLOSED**: forget to set the tenant and the policy returns nothing. It gives the answer the
buyer wants — *"isolation is enforced by the database, not by our application code; a bug, a raw
query or a management command cannot cross the boundary"* — with no schema migration and no change to
the deployment topology.

Application-layer scoping stays as the first line; RLS is the safety net beneath it.

### D3 — Two prerequisites, both showstoppers, both measured

**P1 — the app DB role currently bypasses RLS entirely.**
```
current_user: autosec    rolsuper: True    rolbypassrls: True
```
Policies would be silently ignored in production while every test passed. Requires a dedicated app
role that is not superuser, not `BYPASSRLS`, and not the table owner — or `ALTER TABLE … FORCE ROW
LEVEL SECURITY` on every protected table.

**P2 — PgBouncer transaction pooling makes the textbook pattern a leak.**
We pool in transaction mode (`base.py:21` — *"transaction pooling hands a server connection back
after each transaction"*). The standard middleware pattern, `SET app.current_tenant_id = …`, is
**session-scoped**: the value persists on a pooled connection that is then handed to a different
tenant's transaction, and RLS serves tenant B tenant A's rows. It must be **`SET LOCAL` inside an
explicit transaction**, and every Celery task must open one.

**Neither is optional. A partially-applied RLS rollout looks secure and is not** — which is precisely
the failure class this codebase spent 2026-08-13 removing (ten separate guards found that existed and
could not fire).

### D4 — Prove the policy before trusting it.

The first artifact of Phase 0 is a **test that watches a policy DENY**, executed as the real
non-superuser application role. No policy is trusted until it has been observed blocking something.
This is the same discipline as `PatchAttestation` (ADR 0025 P2c) and `PRICE_TABLE_VERSION`: a control
that has never been seen to fire is not a control.

### D5 — "Run my own tenant" is answered by DEPLOYMENT, not database routing.

A dedicated stack — own k3s, own Postgres, own bucket — gives complete isolation, requires **zero
application change**, and the Terraform is already parameterised per workload. That is the enterprise
tier, and it is the honest answer to a buyer who does not want to trust our isolation claims: *then
don't — run your own instance.*

`django-tenants` (schema-per-tenant) solves a different problem: running **many** tenants efficiently
in one deployment. At zero customers that is a multi-week migration across 30+ persistence apps to
optimise a scale we do not have. Recorded as the documented path if a contract ever requires schema
separation; not now.

## Plan

**Phase 0 — prerequisites.** Non-superuser app role · `FORCE ROW LEVEL SECURITY` · `SET LOCAL` in a
transaction · the deny-proof test (D4) first.

**Phase 1 — the forgotten-filter defence.** A tenant-scoped model/manager that filters by default,
with an explicit `unscoped` escape hatch, and automatic tenant assignment on save. This solves #83's
bug class structurally rather than one query at a time.

**Phase 2 — RLS on customer-data tables**, highest value first: `Finding`, `FindingRisk`, board
`Task`, scan artefacts.

**Phase 3 — the adjacent leaks.** Tenant-prefixed cache keys (a shared cache key is the same leak by
another route); composite `(workspace, …)` indexes (`Finding` already has them).

**Alongside:** fix #83, run the #133 authz audit, and add the mass-assignment test — a client that
supplies another tenant's id must have it ignored, and a foreign object must return 404, not 403.

## Consequences

We can state our isolation posture precisely and defensibly: application-enforced scoping, backed by
database-enforced RLS, audited, with a dedicated-deployment option above it. That is a normal, honest
answer for an early company — and unlike "we have database-level separation", it is one we can prove.

Until Phase 0 lands, the honest answer remains: *isolation is application-enforced, tested in places,
with known gaps we are closing.* Say that, not more.

We also inherit an obligation from ADR 0026, which pairs with this: we deliberately do not persist
embeddings of customer code (embedding inversion reconstructs 92%+ of source). "We don't keep a copy
of your code" is the companion answer to the same buyer's question about the risk of aggregating this
much customer data.

## References

- Task #147 (build), #83 (known leak), #133 (authz audit), #122 (cross-tenant assertions)
- ADR 0026 — code retrieval: agentic search, not embeddings
- testdriven.io/blog/django-multi-tenant — the three approaches and their trade-offs
- PostgreSQL RLS: `FORCE ROW LEVEL SECURITY`, `current_setting()`, and the `BYPASSRLS`/owner caveats
