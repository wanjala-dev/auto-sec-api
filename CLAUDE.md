# CLAUDE.md — Auto-Sec API (autosec)

Guidance for Claude Code when working in this repo. **"autosec" = Auto-Sec (Automatic Security)** — use it
everywhere (branches, scripts, dirs, prose); it's the canonical short name.

## What this is

**Auto-Sec** is an **enterprise "Kali-Linux-for-SOC"** platform — a blue/green-team
security product whose core is a **deep-agent arm**: an orchestrator/planner that routes security
alerts (Slack, Sentry, CloudWatch) to specialist triage sub-agents that read logs, inspect git,
call tools/MCPs, and surface root-cause context — taking toil and alert fatigue off on-call teams.
The arm is designed to be **reproducible** (a blueprint other arms — OSINT, recon, enumeration —
plug into) and eventually **shareable/open-source-able**. Built to scale, be extended, and be
worked on by many agents and people.

Stack: **Django 6.0 + DRF + Celery**, **Explicit Architecture** (DDD + Hexagonal + Onion + Clean +
CQRS), strict bounded-context boundaries. PostgreSQL (pgvector), Redis, Channels. LangChain /
LangGraph agent framework with pgvector RAG + Langfuse tracing.

## Provenance — this is a FORK, know how it was built

autosec was **forked, not written from scratch**:
- **Backend** copied from the Wanjala nonprofit API (`/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0`),
  then the nonprofit domain was **stripped** and the security-relevant + SaaS foundation kept.
- **Frontend** (`../auto-sec-frontend`) mirrors literacyseed's stack and renders its **"V2"
  HUD** (a sci-fi SOC command-center) **1:1**.

**Kept bounded contexts** (`components/`): `identity` (full auth: email+password, Google OAuth,
magic link, OTP/2FA, JWT, password reset, sessions, login activity), `workspace` (the
**organization** — tenant/org container + admin), `team`, `project`, `membership`, `shared_kernel`,
`shared_platform` (**feature flags** — gate in-progress features from day one), `workflow`
(automation engine), `agents` (the deep-agent framework + LangGraph orchestrator + test harness),
`knowledge` (pgvector RAG + embeddings + LLM factory), `audit` (immutable trail), `notifications`,
`recycle_bin` (soft-delete/tombstone), `sign_off` (approval gate for high-risk actions), and the
**SaaS billing** stack: `subscription` (tiers/pricing/entitlements), `money` (currency SSOT),
`payments` (Stripe, org/team-plan billing, payment methods, payment plans, webhooks).

**Removed** (nonprofit domain — do NOT re-add without cause): sponsorship, budgeting, grants,
commerce/marketplace, contacts, content, social, campaigns, events, donation_forms, reports,
receipts, recommendations, messaging, admin_verification, sharing, templates, landing, sectors, faq,
elasticsearch/search, and the multi-DB tenant router (autosec is **single-DB**).

**Security posture is first-class** (this will be probed by hackers): audit logging, notifications
for security events, recycle-bin tombstoning, sign-off approvals, JWT + DRF throttles, account
lockout + OTP policies, `@sensitive_post_parameters` scrubbing, PII-safe logging, and the
`honeypot` app (trap endpoints) are all kept and must not be weakened.

## How to self-correct when the fork bites

The strip introduced a few standing patterns — if something breaks, check these first:
- **Deleted-module import** → some file still imports a removed context. Grep for it, then either
  delete the domain-only file or edit out the reference (keep the framework).
- **Migrations were reset to fresh `0001`s** (the copied history referenced deleted apps). If you
  add a model, `makemigrations` extends the fresh graph normally.
- **Payment ledger models** (`PaymentMethod`/`Plan`/`Event`/`Order`/…) live under the **`workspaces`**
  app (imported at the bottom of `infrastructure/persistence/workspaces/models.py`), NOT a separate
  app. Their migrations are in `workspaces/migrations/`.
- **`api/celery.py` side-effect imports** are protected by a ruff per-file-ignore
  (`pyproject.toml`) — don't "clean up" those imports; they register Celery tasks.
- Nonprofit `bootstrap_dev` was replaced by a minimal `createsuperuser` + `seed_subscription_tiers`
  in `docker/scripts/start-web.sh`.

## Running it locally (isolated from the source repo)

The compose project is renamed **`auto_sec`** (set in `.env` as `COMPOSE_PROJECT_NAME`) with
**distinct host ports** so it coexists with the source `api-v2.0` stack (which resolves to project
`compose`). **Never** run compose without the autosec `.env`.

```bash
# from auto-sec-api/
docker compose --env-file .env \
  -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.local.yml \
  up -d web celery_worker celery_ai_teammate_worker celery_beat
```

- **Web/API:** http://localhost:8020  (health: `curl http://localhost:8020/api/health/` → `{"status":"ok"}`)
- **DB:** `auto_sec-db-1` on host `:5442` (pgvector). **Redis** `:6389`. **PgBouncer** `:6443`.
- Container names are `auto_sec-<svc>-1`. Run Django commands via
  `docker exec auto_sec-web-1 python manage.py <cmd>`.
- The startup script runs migrate + `seed_subscription_tiers` (Free/Pro/Premium) +
  `seed_feature_flags` + a minimal superuser (`admin` / `$SUPER_USER_PASSWORD`).

**Frontend runs on http://localhost:3001** (3000 is the original literacyseed). See the frontend
repo's CLAUDE.md.

## Testing

```bash
docker exec -e DJANGO_SETTINGS_MODULE=api.settings.test auto_sec-web-1 python -m pytest tests/architecture/
```
Architecture tests enforce the import boundaries — keep them green (a few fork-drift fixtures may
still need trimming; fix the fixture, never baseline a real violation).

## Standards (inherited from the source — still HARD RULES)

- **Explicit Architecture** — the rule files in `.claude/rules/` are authoritative:
  `architecture-manifesto.md`, `bounded-context-structure.md`, `django-conventions.md`,
  `persistence-and-orm.md`, `performance.md`, `logging.md`, `repo-hygiene.md`, `no-shortcuts.md`,
  `branching-strategy.md`. Read them before structural changes.
- **No shortcuts / bandaids** — recommend the root fix, never a symptom-masking stepping-stone.
- **Reuse, don't reinvent** — grep for an existing model/service/adapter/util before building new.
- **After model changes:** `makemigrations` + `migrate`; write + run unit tests for new
  domain/use-cases.
- **Money is load-bearing** — the SaaS billing (subscription/payments/Stripe) is baked in from day
  one because autosec is a product that will bill customers as it scales. Treat payment-path changes
  with care; verify against the Stripe MCP where connected.

## Directory layout

- `components/` — bounded contexts (business logic; the list above).
- `infrastructure/` — persistence (`infrastructure/persistence/<app>/`), Celery, API infra, storage.
- `api/` — Django project (settings, urls, celery, wsgi/asgi). Single-DB; `DATABASE_ROUTERS = []`.
- `tests/architecture/` — import-boundary enforcement.
- `.claude/` — rules, hooks, commands, agents (autosec-scoped; some source rules were trimmed).
