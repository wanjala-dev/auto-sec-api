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

## Running it locally (Kubernetes — Docker Desktop)

Auto-Sec runs on **local Kubernetes** (Docker Desktop's built-in cluster) in namespace
**`autosec`** — the docker-compose stack was **retired (2026-07-26)**. The Kustomize manifests live
in the separate **`auto-sec-infra`** repo (`git@github.com:wanjala-dev/auto-sec-infra.git`, cloned
at `/Users/henrywanjala/Desktop/auto-sec/auto-sec-infra`); that repo's **`k8s/README.md` is the
source of truth** for the base-image build and the full apply. The two key commands:

```bash
# from auto-sec-infra/ — bake THIS repo's source into the app image, then apply the local overlay
docker build -t autosec-api:local -f k8s/local-image.Dockerfile \
  /Users/henrywanjala/Desktop/auto-sec/auto-sec-api          # local-image.Dockerfile is FROM auto-sec-backend:dev
kubectl apply -k k8s/overlays/local
```

- **Web/API:** the nginx **ingress** at `http://autosec.local` (add `127.0.0.1 autosec.local` to
  `/etc/hosts`). Health: `curl http://autosec.local/api/health/` → `{"status":"ok"}`. Or
  port-forward: `kubectl -n autosec port-forward svc/api 8000:8000`.
- **Namespace `autosec`.** Deployments: `api`, `channels`, `celery-worker`,
  `celery-ai-teammate-worker`, `celery-beat`, `scanning-worker`, `trivy-server`; StatefulSet
  `postgres` (pgvector); `redis`. Inspect with `kubectl -n autosec get pods` /
  `kubectl -n autosec logs deploy/<svc>` (or `k9s`).
- Run Django commands via **`kubectl exec -n autosec deploy/api -- python manage.py <cmd>`**.
- On `apply`, a migrate Job runs migrations and the api startup seeds `seed_subscription_tiers`
  (Free/Pro/Premium) + `seed_feature_flags` + a minimal superuser (`admin` / `$SUPER_USER_PASSWORD`).

**Frontend is NOT on this cluster** — the k8s stack is backend-only (no frontend namespace,
deployment, or manifest). The frontend runs separately from its own repo (a host dev server,
historically `http://localhost:3001`); see the frontend repo's CLAUDE.md.

## Testing

```bash
kubectl exec -n autosec deploy/api -- env DJANGO_SETTINGS_MODULE=api.settings.test \
  python -m pytest tests/architecture/
```
The test settings (`api.settings.test`) use **SQLite** (no external Postgres), so the suite also
runs in any throwaway container built from the app image — handy for testing a worktree's code
without touching the cluster:
```bash
docker run --rm --entrypoint python autosec-api:local -m pytest tests/architecture/
```
Architecture tests enforce the import boundaries — keep them green (a few fork-drift fixtures may
still need trimming; fix the fixture, never baseline a real violation).

## Standards (inherited from the source — still HARD RULES)

- **Explicit Architecture** — the rule files in `.claude/rules/` are authoritative:
  `architecture-manifesto.md`, `bounded-context-structure.md`, `django-conventions.md`,
  `persistence-and-orm.md`, `performance.md`, `logging.md`, `repo-hygiene.md`, `dry-reuse.md`,
  `no-shortcuts.md`, `verify-dont-guess.md`, `improve-dont-replicate.md`, `pin-versions.md`,
  `branching-strategy.md`, `skills-and-plugins.md`. Read them before structural changes. For structural/CNAPP work, **load
  the architecture skill first** (`.claude/skills/architecture/SKILL.md` — the hub-and-spoke target
  + C1–C7 decoupling rules).
- **Verify, don't guess** — this is a fork; when something feels off, ground it (research online +
  MCPs, load the architecture skill, check the live system) before building on it. See
  `verify-dont-guess.md`.
- **Improve, don't replicate** — don't blindly copy the fork's existing pattern; when there's room
  to improve (a superseded tool, fragile coupling, dead drift), dig in and fix it as you see it. See
  `improve-dont-replicate.md`.
- **Pin versions, never `:latest`** — this is a security tool; every container image / dependency is
  pinned to an explicit version (a digest for images we execute). See `pin-versions.md`.
- **No shortcuts / bandaids** — recommend the root fix, never a symptom-masking stepping-stone.
- **Reuse, don't reinvent** — grep for an existing model/service/adapter/util before building new.
- **After model changes:** `makemigrations` + `migrate`; write + run unit tests for new
  domain/use-cases.
- **Money is load-bearing** — the SaaS billing (subscription/payments/Stripe) is baked in from day
  one because autosec is a product that will bill customers as it scales. Treat payment-path changes
  with care; verify against the Stripe MCP where connected.

## Git & worktrees — ALWAYS work in a worktree (HARD RULE)

autosec is **TRUNK-BASED**: the primary clones (`auto-sec-api`, `auto-sec-frontend`) sit on
`main`. A PreToolUse guard hook runs `git branch --show-current` before **every** Bash command and
**blocks it when the shell's cwd is on `main`/`master`** — and it blocks *everything* (`docker`,
`gh`, `pytest`, even `cd`), not just pushes. If the shell's working directory drifts onto a
main-branch clone, ALL Bash is wedged until that clone is checked out to a non-main branch or the
session restarts (you can't `cd` out — `cd` is itself Bash and gets blocked first).

**So, without exception:**

1. **Do ALL work in a git worktree on a feature branch off `origin/main`** — never in a primary
   clone:
   ```bash
   git -C /Users/henrywanjala/Desktop/auto-sec/auto-sec-api fetch origin
   git -C /Users/henrywanjala/Desktop/auto-sec/auto-sec-api worktree add \
     /Users/henrywanjala/Desktop/auto-sec/worktrees/<name> -b feat/<name> origin/main
   ```
   Then `cd` into the worktree and run everything from there. The worktree is on a feature branch, so
   Bash never trips the guard.
2. **Never `cd` into a primary clone.** If you must touch one (start its dev server, read a file via
   shell), wrap the `cd` in a **subshell** so the cwd never persists — `( cd <clone> && npm start ) &`
   — or use `git -C <path>` / absolute paths. Prefer the Read tool for reading files (no cwd effect).
3. **Ship from the worktree:** commit + `gh pr create --base main`, `gh pr merge --squash
   --delete-branch`, then `git worktree remove <path>`. Sync the primary clone with
   `git -C <clone> checkout main && git -C <clone> pull` (from a safe cwd, e.g. via `git -C`).

Never `Co-Authored-By: Claude` on autosec commits. See `.claude/rules/branching-strategy.md`.

## Directory layout

- `components/` — bounded contexts (business logic; the list above).
- `infrastructure/` — persistence (`infrastructure/persistence/<app>/`), Celery, API infra, storage.
- `api/` — Django project (settings, urls, celery, wsgi/asgi). Single-DB; `DATABASE_ROUTERS = []`.
- `tests/architecture/` — import-boundary enforcement.
- `.claude/` — rules, hooks, commands, agents (autosec-scoped; some source rules were trimmed).

## Skills — enable the plugin, never copy it

Shared engineering skills (`agents`, `celery-tasks`, `logging`, `sql`, `testing`, `identity`,
`user-model`, `api-versioning`, `workflow`) come from the **`wanjala-core@wanjala-kit`
plugin**, enabled in `.claude/settings.json`. autosec deliberately does **not** enable
`wanjala-nonprofit` — those skills describe grants/sponsorship/donations, the domain this
fork stripped.

`.claude/skills/` holds autosec-only skills (`architecture` = the CNAPP hub-and-spoke
target, `tenancy` = the two-tier pooled/dedicated model plus the traps that have already
bitten this codebase, `integrations`, `personas`, `templates`, `backup-recovery`,
`gtm-qa-sweep`).
**Never copy a kit skill in here** — on 2026-08-11 a five-week-stale copy of the `agents`
skill (found by grepping the filesystem, because the plugin wasn't enabled) drove an
architecture decision from a document predating `RubricMiddleware` entirely. If you ever
find yourself grepping for a SKILL.md, stop: the plugin isn't loaded and whatever you find
is unowned. See `.claude/rules/skills-and-plugins.md`.
