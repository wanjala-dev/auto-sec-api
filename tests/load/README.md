# Load + Smoke Tests

Locust-based smoke + load testing for the Wanjala API. Single tool, two profile families: smoke (1 user, 30s) and load (Avg / Spike / Stress / Soak shapes).

The rules for what lives here, what's forbidden, and what NOT to test live in **`.claude/rules/load-testing.md`**. Read that first if you haven't.

## Quick start

```bash
# 1. Install deps (one time)
pip install -r requirements/development.txt

# 2. Seed the dedicated load-test user + workspace (one time per environment, idempotent)
docker exec compose-web-1 python manage.py seed_load_test_user

# 3. Copy the env template — defaults match the seed command's defaults
cp tests/load/env.load.sample tests/load/.env.load
# Optionally: paste the LOAD_SMOKE_WORKSPACE_ID printed by the seed command

# 4. Run a 30s local smoke against your Docker stack
make smoke

# 5. Or open the Locust web UI for ad-hoc exploration
make load-ui
```

The seed command (`components/shared_platform/cli/management/commands/seed_load_test_user.py`) provisions a dedicated `loadtest@wanjala.local` user, a `Load Test Workspace` teamspace, and an owner-role membership. Idempotent — safe to re-run. Override defaults via `LOAD_TEST_EMAIL`, `LOAD_TEST_PASSWORD`, `LOAD_TEST_WORKSPACE` env vars at seed time. **Do not** reuse `bootstrap_dev` personas — those drift between branches and depend on a pre-existing teamspace. See `.claude/rules/load-testing.md` §8a.

## What's here

| File | Purpose |
|---|---|
| `locustfile.py` | Single Locust entrypoint. Imports HttpUsers + shapes. |
| `config.py` | `pydantic-settings` config — target, profile, base URLs, creds. |
| `auth.py` | JWT login + proactive refresh helpers. |
| `shapes.py` | `SmokeShape`, `AvgShape`, `SpikeShape`, `StressShape`, `SoakShape`. |
| `base_users.py` | `AnonymousHttpUser`, `AuthenticatedHttpUser` base classes. |
| `scenarios/` | Per-context HttpUser subclasses (one file per context). |
| `journeys/` | Cross-context end-to-end flows (sponsor donation, contributor dashboard). |
| `reports/` | Locust HTML + CSV output (gitignored). |

## Running the canonical profiles

```bash
make smoke          # SmokeShape, target=local — 30s sanity check
make smoke-demo     # SmokeShape, target=demo — post-deploy verify
make load-avg       # AvgShape, target=local — 5min ramp + 30min hold + 5min ramp @ 50 users
make load-spike     # SpikeShape, target=local — 0→500→0 in 4 minutes
make load-stress    # StressShape, target=local — 0→200→0 over 45 minutes
make load-ui        # Locust web UI on http://localhost:8089
```

Soak (`SoakShape`, 4h @ 100 users) is intentionally NOT a Make target — invoke manually from a stable host:

```bash
LOAD_PROFILE=soak locust --headless -f tests/load/locustfile.py \
  --shape=SoakShape --host=http://localhost:8000 \
  --html=tests/load/reports/soak-$(date +%Y%m%d-%H%M).html \
  --csv=tests/load/reports/soak-$(date +%Y%m%d-%H%M)
```

## Targeting demo vs local

`LOAD_TARGET` defaults to `local` (`http://localhost:8000`). To hit demo:

```bash
LOAD_TARGET=demo make smoke      # equivalent to `make smoke-demo`
```

A misfired `make load-stress` will never hit demo — only `smoke-demo` reaches the demo URL by default. Hitting demo with anything else requires manually setting `LOAD_TARGET=demo`, which is intentional friction.

## What NOT to do

The full list lives in `.claude/rules/load-testing.md` §6. Highlights:

- ❌ Don't run load tests against demo with anything heavier than `SmokeShape`. Demo shares its DB and Redis with the actual nonprofit demo.
- ❌ Don't hit Stripe webhook routes. Don't exercise donation checkout. Read-only smoke + load only.
- ❌ Don't use real customer credentials. Use the dedicated `seed_load_test_user` (provisions `loadtest@wanjala.local`).
- ❌ Don't bake an access token into env vars. Always login → cache → refresh.
- ❌ Don't add a new tool alongside Locust (no pytest-as-smoke, no k6, no httpx scripts). One tool.

## Adding a scenario

1. Pick the right context file in `scenarios/` (e.g. `sponsorship_scenarios.py`). If you're adding a new context, create `<ctx>_scenarios.py` and import it in `locustfile.py`.
2. Add a `@task` method on the existing `<Ctx>LoadUser` class.
3. Use `self.authed("get", "/some/endpoint/")` for authenticated endpoints — never call `self.client.get(...)` directly with a hand-rolled Authorization header.
4. Whitelist expected non-2xx codes if any (e.g. an empty list endpoint that returns 404).
5. Run `make smoke` locally; confirm exit code 0 and 0 failures in the stdout summary.

## Cross-context journeys

Multi-context flows (sponsor → workspace → recipients → donations) live in `journeys/`. They model real user paths where a single context's scenario file would be misleading (the journey crosses contexts by design).

When in doubt about per-context vs journey: if the test would be wrong if any one of the contexts it touches went down, it's a journey. If only one context's failure breaks it, it's a per-context scenario.

## Runbook — when the operator says X, do Y

This section is the contract for any human or agent acting on a smoke/load request. If you're an agent and the operator says **"run smoke"** or **"run a smoke test"**, follow the local recipe verbatim. If they say **"run smoke against demo"** or **"smoke the deploy"**, use the demo recipe.

### Recipe: "run smoke" (local)

```bash
# 1. Container deps — once per fresh image, no-op after make build
docker exec compose-web-1 sh -c 'command -v locust >/dev/null 2>&1' || make install-load-deps

# 2. Migration drift — make smoke fails here if the local DB is behind
docker exec compose-web-1 python manage.py migrate --check
# If it reports unapplied migrations:
#   docker exec compose-web-1 python manage.py migrate
# If it errors with "column ... already exists" (manual schema drift):
#   docker exec compose-web-1 python manage.py migrate <app> <NNNN_full_name> --fake
#   docker exec compose-web-1 python manage.py migrate
# Investigate what 0NNN actually does before --fake'ing it; see Failure modes below.

# 3. Seed the load-test user (idempotent — safe re-run)
docker exec compose-web-1 python manage.py seed_load_test_user
# Note the printed LOAD_SMOKE_WORKSPACE_ID; you'll pass it via env or .env.load.

# 4. Run smoke
make smoke
# OR with explicit env (skips the .env.load file):
docker exec \
  -e LOAD_TARGET=local -e LOAD_PROFILE=smoke \
  -e LOAD_SMOKE_EMAIL=loadtest@wanjala.local \
  -e LOAD_SMOKE_PASSWORD=loadtest-dev-only-password \
  -e LOAD_SMOKE_WORKSPACE_ID=<from-step-3> \
  -e PYTHONPATH=/app \
  compose-web-1 locust --headless -f tests/load/locustfile.py \
  --host=http://localhost:8000 --exit-code-on-error 1 \
  --html=tests/load/reports/smoke.html

# 5. Verify
# - Exit code 0
# - Locust prints "13 reqs, 0 fails (0.00%)"
# - HTML at tests/load/reports/smoke.html
```

### Recipe: "run smoke against demo" / "smoke the deploy"

```bash
# 1. Seed the load-test user on EC2 — once per environment, after deploy.
#    Use a strong password via LOAD_TEST_PASSWORD; do NOT commit demo creds.
ssh -i $KEY_PATH ubuntu@$EC2_IP \
  "docker exec -e LOAD_TEST_PASSWORD=<strong> compose-web-1 \
   python manage.py seed_load_test_user"

# 2. Put the printed creds + workspace_id into your local tests/load/.env.load
#    or pass via env at run time. Demo creds live ONLY on your laptop.

# 3. Run smoke against the public URL
make smoke-demo

# 4. Verify
# - Exit code 0
# - All 13 endpoints 2xx
# - Compare smoke.html durations to the local baseline; demo + 100ms is normal.
```

`make smoke-demo` is the canonical post-deploy verify. The pre-deploy gate (the pytest gate in CLAUDE.md) catches code regressions; smoke-demo catches env-level regressions (DB connection, certificate expiry, env-var typos, vendor test-mode outage). They answer different questions; both are mandatory for an EC2 ship.

### Recipe: "run a load test" (avg / spike / stress / soak)

```bash
# Same steps 1-3 as the local smoke recipe (deps, migrate, seed).
# Then pick a profile:
make load-avg       # 50 VU, ~40min
make load-spike     # 0→500→0, ~4min
make load-stress    # 200 VU, ~45min

# Soak intentionally has no Make target — invoke from a stable host:
LOAD_PROFILE=soak locust --headless -f tests/load/locustfile.py \
  --shape=SoakShape --host=http://localhost:8000 \
  --html=tests/load/reports/soak-$(date +%Y%m%d-%H%M).html
```

Heavier profiles MUST stay on `LOAD_TARGET=local`. Hitting demo with anything beyond `SmokeShape` shares the demo's Postgres + Redis with paying users — see `.claude/rules/load-testing.md` §5.

## Failure modes — known smoke errors and what they mean

If smoke fails on one of these, the fix is the seed or the local environment, NOT the harness.

| Symptom | Cause | Fix |
|---|---|---|
| `POST /identity/login/` → 401 `{"detail":"Email is not verified"}` | Seeded user is missing `is_verified=True` | Re-run `seed_load_test_user` (current version sets it). If still failing, your local DB has a stale user — check with `python manage.py shell` |
| `POST /identity/login/` → 401 `{"otp_required":true}` | Seeded user has 2FA on (shouldn't happen with this seed; bootstrap_dev personas can have it) | Use the load-test seed, NOT bootstrap_dev personas |
| `GET /workspaces/[id]/setup-status/` → 404 | Workspace `status='inactive'` (default), filtered out of `Workspace.objects` | Re-run `seed_load_test_user` (current version sets `status='active'`) |
| `GET /sponsorship/donations/[ws]/` → 403 | `WorkspaceMembership.workspace_role` is null; Phase 2 RBAC denies | Re-run `seed_load_test_user` (current version attaches the system Owner role) |
| `GET /sponsorship/donations/[ws]/` → 403 while membership is FULLY correct (intermittent, run-to-run) | The sponsor-browse journey's `list_workspaces` adopted `results[0]` of `/workspaces/` — a directory that includes NON-member workspaces — clobbering the configured `LOAD_SMOKE_WORKSPACE_ID`, so member-only tasks hit a foreign workspace and got a correct-RBAC deny | Fixed 2026-07-06: the configured id always wins; discovery is only the fallback when `LOAD_SMOKE_WORKSPACE_ID` is unset. Ensure `.env.load` carries the id printed by `seed_load_test_user` |
| `GET /api/health/celery/` → 503 (first call only) | Celery inspector cold start; first call exceeds the 1s timeout | Re-run smoke; subsequent calls return 200 in <50ms. If it persists, `docker ps --filter name=compose-celery` to confirm workers are up |
| `make smoke` → "locust: command not found" | Locust isn't in the running web image | `make install-load-deps` (one-shot pip install into the running container), or `make build && make restart` (rebuilds image with deps from `requirements/development.txt`) |
| `make smoke` → "ModuleNotFoundError: No module named 'tests.load'" | A `tests` package in site-packages is shadowing `tests/` | Already handled by `tests/__init__.py` + sys.path reordering in locustfile.py. If you still hit this, check git status — those files may be missing |
| `make migrate` → "column X already exists" | Schema drift — column was added manually but the migration row isn't recorded | `migrate <app> <NNNN_full_name> --fake`, then `migrate`. Read the migration first to confirm `--fake` is safe |
| Workspace shows up empty in seed but errors with "FK does not exist" on membership | Multi-tenant router routing inconsistently in management commands | Already handled by `set_db_for_router("default")` + `using="default"` in the seed. If you hit this in NEW seed code, mirror the pattern |

If you see a new failure mode, document it here. The runbook is the source of truth for "what does smoke X mean and what do I do about it."

## Reports

`tests/load/reports/` is gitignored. Each run produces:
- `report.html` — Locust's HTML report (open in a browser)
- `stats_*.csv` — per-endpoint stats

Default-free workflow: open the HTML locally. If you want to keep a record of a specific run (e.g. before a launch), upload manually:

```bash
aws s3 cp tests/load/reports/avg-2026-05-09.html \
  s3://wanjala-load-reports/avg-2026-05-09.html --profile octo-tf-admin
```

There is no automated upload pipeline. Reports stay local by default.
