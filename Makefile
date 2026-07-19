VENV := env
BIN := $(VENV)/bin
PYTHON := $(BIN)/python
SHELL := /bin/bash

include .env

# ── Docker Compose paths ─────────────────────────────────────────────────────
COMPOSE_BASE    := docker/compose/docker-compose.yml
COMPOSE_LOCAL   := docker/compose/docker-compose.local.yml
COMPOSE_STAGING := docker/compose/docker-compose.staging.yml
COMPOSE_PROD    := docker/compose/docker-compose.prod.yml
COMPOSE_EC2     := docker/compose/docker-compose.ec2.yml

DC_LOCAL   := docker compose --env-file .env -f $(COMPOSE_BASE) -f $(COMPOSE_LOCAL)
DC_STAGING := docker compose --env-file .env -f $(COMPOSE_BASE) -f $(COMPOSE_STAGING)
DC_PROD    := docker compose --env-file .env -f $(COMPOSE_BASE) -f $(COMPOSE_PROD)
DC_EC2     := docker compose --env-file .env -f $(COMPOSE_BASE) -f $(COMPOSE_EC2)

.PHONY: help
help: ## Show this help
	@egrep -h '\s##\s' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local Python (non-Docker) ────────────────────────────────────────────────

.PHONY: venv
venv: ## Make a new virtual environment
	python3 -m venv $(VENV) && source $(BIN)/activate

.PHONY: install
install: venv ## Make venv and install requirements
	$(BIN)/pip install --upgrade -r requirements/development.txt

freeze: ## Pin current dependencies
	$(BIN)/pip freeze > requirements/development.txt

.PHONY: run
run: ## Run the Django server (local, no Docker)
	$(PYTHON) manage.py runserver

start: install migrate run ## Install requirements, apply migrations, then start dev server

# ── Docker: Local Development ────────────────────────────────────────────────

.PHONY: up
up: ## Start local Docker stack (detached)
	$(DC_LOCAL) up --build -d

.PHONY: up-attached
up-attached: ## Start local Docker stack (foreground, logs visible)
	$(DC_LOCAL) up --build

.PHONY: down
down: ## Stop local Docker stack
	$(DC_LOCAL) down

.PHONY: restart
restart: down up ## Restart local Docker stack

.PHONY: build
build: ## Build dev Docker image
	$(DC_LOCAL) build

.PHONY: logs
logs: ## Tail logs from all Docker services
	$(DC_LOCAL) logs -f

.PHONY: logs-web
logs-web: ## Tail logs from web service
	$(DC_LOCAL) logs -f web

.PHONY: logs-celery
logs-celery: ## Tail logs from all celery workers
	$(DC_LOCAL) logs -f celery_worker celery_ai_teammate_worker celery_aggregations_worker celery_beat

.PHONY: logs-stripe
logs-stripe: ## Tail logs from the Stripe CLI webhook forwarder
	$(DC_LOCAL) logs -f stripe_webhooks

.PHONY: stripe-webhook-secret
stripe-webhook-secret: ## Print the stable Stripe CLI webhook signing secret (one-time .env setup)
	@echo "Fetching Stripe CLI webhook signing secret (test mode)…"
	@secret=$$(docker run --rm stripe/stripe-cli:latest listen --api-key $(STRIPE_SECRET_KEY) --print-secret 2>/dev/null); \
	if [ -z "$$secret" ]; then \
		echo "Failed to fetch secret. Is STRIPE_SECRET_KEY set in .env to a sk_test_… key?"; exit 1; \
	fi; \
	echo ""; \
	echo "Stripe CLI webhook signing secret: $$secret"; \
	echo ""; \
	echo "Set all three in .env (one CLI session signs every event), then 'make restart':"; \
	echo "  STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=$$secret"; \
	echo "  STRIPE_WEBHOOK_KEY=$$secret"; \
	echo "  STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET=$$secret"

.PHONY: ps
ps: ## Show running Docker services
	$(DC_LOCAL) ps

# ── Docker: Django shortcuts ─────────────────────────────────────────────────

.PHONY: shell
shell: ## Open Django shell in Docker web container
	$(DC_LOCAL) exec web python manage.py shell

.PHONY: bash
bash: ## Open bash in Docker web container
	$(DC_LOCAL) exec web bash

migrate: ## Make and run migrations (Docker or local)
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec web python manage.py makemigrations; \
		$(DC_LOCAL) exec web python manage.py migrate; \
	else \
		$(PYTHON) manage.py makemigrations; \
		$(PYTHON) manage.py migrate; \
	fi

# Force pytest to use `api.settings.test` (SQLite under .pytest-dbs/) even when
# the container env or the developer's shell has `DJANGO_SETTINGS_MODULE`
# pointing at `api.settings.local`. `addopts = --ds=…` in pytest.ini is the
# primary defence; these env overrides are belt-and-suspenders for raw `make
# test*` invocations.
PYTEST_DOCKER_ENV := -e DJANGO_SETTINGS_MODULE=api.settings.test
PYTEST_LOCAL_ENV := DJANGO_SETTINGS_MODULE=api.settings.test

.PHONY: test
test: ## Run full test suite (--reuse-db is default; use test-fresh after model changes)
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest -x -q; \
	fi

.PHONY: test-fresh
test-fresh: ## Rebuild test DB from current models (run after model changes break --reuse-db)
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest --create-db -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest --create-db -x -q; \
	fi

.PHONY: test-unit
test-unit: ## Run unit tests only (component domain + application logic)
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest components/*/tests/unit/ -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest components/*/tests/unit/ -x -q; \
	fi

.PHONY: test-integration
test-integration: ## Run integration tests (component integration + cross-cutting)
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest components/*/tests/integration/ tests/ --ignore=tests/architecture -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest components/*/tests/integration/ tests/ --ignore=tests/architecture -x -q; \
	fi

.PHONY: test-arch
test-arch: ## Run architecture guardrail tests
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest tests/architecture/ -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest tests/architecture/ -x -q; \
	fi

.PHONY: test-context
test-context: ## Run tests for a single context (usage: make test-context CTX=budgeting)
	@if [ -z "$(CTX)" ]; then echo "Usage: make test-context CTX=budgeting"; exit 1; fi
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest components/$(CTX)/tests/ -x -v; \
	else \
		$(PYTEST_LOCAL_ENV) pytest components/$(CTX)/tests/ -x -v; \
	fi

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	@if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^compose-web-1$$'; then \
		docker exec $(PYTEST_DOCKER_ENV) compose-web-1 pytest --cov=components --cov-report=html --cov-report=term-missing -x -q; \
	else \
		$(PYTEST_LOCAL_ENV) pytest --cov=components --cov-report=html --cov-report=term-missing -x -q; \
	fi

.PHONY: test-db-clean
test-db-clean: ## Drop leftover test_* databases from the local Postgres container (pollution from past misruns)
	@if ! docker ps --format '{{.Names}}' | grep -q '^compose-db-1$$'; then \
		echo "compose-db-1 is not running; nothing to clean."; \
	else \
		docker exec -i compose-db-1 sh -c '\
			DBS=$$(psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -tAc \
				"SELECT datname FROM pg_database WHERE datname LIKE '"'"'test_%'"'"';"); \
			if [ -z "$$DBS" ]; then echo "No test_* databases found."; exit 0; fi; \
			for db in $$DBS; do \
				psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c \
					"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '"'"'$$db'"'"' AND pid <> pg_backend_pid();" >/dev/null 2>&1; \
				psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "DROP DATABASE IF EXISTS \"$$db\";"; \
			done'; \
	fi

# ── Load + Smoke Testing (Locust) ──────────────────────────────────────────
# See .claude/rules/load-testing.md for the rules. One tool, no mixing.
#
# Targets prefer Docker (no local venv needed). When the web container is up,
# locust runs inside it via `docker exec`. Inside the container,
# http://localhost:8000 is the local gunicorn — same target the host hits via
# the published port. When the stack is down, targets fall back to a local venv
# at $(BIN)/locust (run `make install` once to provision it).
#
# First-run setup: locust isn't in the running web image yet. Either rebuild
# the image (`make build` + `make restart`) or use `make install-load-deps` for
# a quick pip-install into the running container.

LOAD_FILE := tests/load/locustfile.py
LOCUST_VENV := $(BIN)/locust
LOAD_DC_EXEC := $(DC_LOCAL) exec -T

.PHONY: install-load-deps
install-load-deps: ## First-run helper: pip install locust + pydantic-settings into the running web container
	$(LOAD_DC_EXEC) web pip install --no-cache-dir locust==2.31.5 pydantic-settings==2.5.2

.PHONY: smoke
smoke: ## SmokeShape (1 user, 30s) against local — Docker if up, else venv
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(LOAD_DC_EXEC) -e LOAD_TARGET=local -e LOAD_PROFILE=smoke -e PYTHONPATH=/app web locust --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 --exit-code-on-error 1 \
			--html=tests/load/reports/smoke.html; \
	else \
		LOAD_TARGET=local LOAD_PROFILE=smoke $(LOCUST_VENV) --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 --exit-code-on-error 1 \
			--html=tests/load/reports/smoke.html; \
	fi

.PHONY: smoke-demo
smoke-demo: ## SmokeShape against demo (post-deploy verify) — Docker if up, else venv
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(LOAD_DC_EXEC) -e LOAD_TARGET=demo -e LOAD_PROFILE=smoke -e PYTHONPATH=/app web locust --headless -f $(LOAD_FILE) \
			--host=https://api.wanjala.art --exit-code-on-error 1 \
			--html=tests/load/reports/smoke-demo.html; \
	else \
		LOAD_TARGET=demo LOAD_PROFILE=smoke $(LOCUST_VENV) --headless -f $(LOAD_FILE) \
			--host=https://api.wanjala.art --exit-code-on-error 1 \
			--html=tests/load/reports/smoke-demo.html; \
	fi

.PHONY: qa-demo-smoke
qa-demo-smoke: ## Dispatch the QA demo Playwright smoke (GitHub Actions) + watch it — post-deploy verify
	@echo "Dispatching QA demo smoke workflow…"
	@gh workflow run qa-demo-smoke.yml --ref development
	@sleep 8
	@gh run watch "$$(gh run list --workflow=qa-demo-smoke.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status

.PHONY: load-avg
load-avg: ## AvgShape (50 VU, ~40min) against local — Docker if up, else venv
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(LOAD_DC_EXEC) -e LOAD_TARGET=local -e LOAD_PROFILE=avg -e PYTHONPATH=/app web locust --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/avg.html --csv=tests/load/reports/avg; \
	else \
		LOAD_TARGET=local LOAD_PROFILE=avg $(LOCUST_VENV) --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/avg.html --csv=tests/load/reports/avg; \
	fi

.PHONY: load-spike
load-spike: ## SpikeShape (0→500→0, ~4min) against local — Docker if up, else venv
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(LOAD_DC_EXEC) -e LOAD_TARGET=local -e LOAD_PROFILE=spike -e PYTHONPATH=/app web locust --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/spike.html --csv=tests/load/reports/spike; \
	else \
		LOAD_TARGET=local LOAD_PROFILE=spike $(LOCUST_VENV) --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/spike.html --csv=tests/load/reports/spike; \
	fi

.PHONY: load-stress
load-stress: ## StressShape (200 VU, ~45min) against local — Docker if up, else venv
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(LOAD_DC_EXEC) -e LOAD_TARGET=local -e LOAD_PROFILE=stress -e PYTHONPATH=/app web locust --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/stress.html --csv=tests/load/reports/stress; \
	else \
		LOAD_TARGET=local LOAD_PROFILE=stress $(LOCUST_VENV) --headless -f $(LOAD_FILE) \
			--host=http://localhost:8000 \
			--html=tests/load/reports/stress.html --csv=tests/load/reports/stress; \
	fi

.PHONY: load-ui
load-ui: ## Open Locust web UI on http://localhost:8089 (venv-only — Docker port not published)
	@if [ ! -x "$(LOCUST_VENV)" ]; then \
		echo "load-ui requires a local venv (Docker port 8089 isn't published in docker-compose.local.yml)."; \
		echo "Provision the venv with: make install"; \
		exit 1; \
	fi
	LOAD_TARGET=local $(LOCUST_VENV) -f $(LOAD_FILE) --host=http://localhost:8000

# ── RAG eval harness — tests/eval/rag/ ────────────────────────────────────────
# RAGAS-style eval over the live agentic RAG pipeline. Runs against local by
# default; eval-rag-demo runs against the deployed demo. See
# `tests/eval/rag/README.md` for the runbook + cost expectations.

EVAL_RAG_RUN_ID := $(shell date -u +%Y%m%d-%H%M%S)

.PHONY: eval-rag
eval-rag: ## Run end-to-end RAG eval (collect + score) against local
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec -e EVAL_TARGET=local -e PYTHONPATH=/app web \
			python -m tests.eval.rag.runner --phase all --run-id $(EVAL_RAG_RUN_ID); \
	else \
		echo "Local Docker stack not running. Start it with: make up"; \
		exit 1; \
	fi

.PHONY: eval-rag-demo
eval-rag-demo: ## Run end-to-end RAG eval against demo (REAL LLM cost ~$0.45)
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec -e EVAL_TARGET=demo -e PYTHONPATH=/app web \
			python -m tests.eval.rag.runner --phase all --run-id $(EVAL_RAG_RUN_ID); \
	else \
		echo "Local Docker stack not running. Start it with: make up"; \
		exit 1; \
	fi

.PHONY: eval-rag-collect
eval-rag-collect: ## Run only the collect phase (no judge LLM calls, cheap)
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec -e EVAL_TARGET=local -e PYTHONPATH=/app web \
			python -m tests.eval.rag.runner --phase collect --run-id $(EVAL_RAG_RUN_ID); \
	else \
		echo "Local Docker stack not running. Start it with: make up"; \
		exit 1; \
	fi

.PHONY: eval-rag-score
eval-rag-score: ## Score an existing collected run record. Usage: make eval-rag-score RUN_FILE=tests/eval/rag/reports/run-<id>.json
	@if [ -z "$(RUN_FILE)" ]; then \
		echo "Usage: make eval-rag-score RUN_FILE=tests/eval/rag/reports/run-<id>.json"; \
		exit 1; \
	fi
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec -e PYTHONPATH=/app web \
			python -m tests.eval.rag.scorer --run-id rescore-$(EVAL_RAG_RUN_ID) --run-record-path $(RUN_FILE); \
	else \
		echo "Local Docker stack not running. Start it with: make up"; \
		exit 1; \
	fi

.PHONY: createsuperuser
createsuperuser: ## Create a Django superuser (Docker)
	$(DC_LOCAL) exec web python manage.py createsuperuser

.PHONY: seed-ai-models
seed-ai-models: ## Seed AI model catalog (providers + models)
	@if $(DC_LOCAL) ps web --status running -q 2>/dev/null | grep -q .; then \
		$(DC_LOCAL) exec web python manage.py seed_ai_models --available; \
	else \
		$(PYTHON) manage.py seed_ai_models --available; \
	fi

# ── Docker: Staging ──────────────────────────────────────────────────────────

.PHONY: up-staging
up-staging: ## Start staging stack
	$(DC_STAGING) up --build -d

.PHONY: down-staging
down-staging: ## Stop staging stack
	$(DC_STAGING) down

.PHONY: logs-staging
logs-staging: ## Tail staging logs
	$(DC_STAGING) logs -f

# ── Docker: Production ───────────────────────────────────────────────────────

.PHONY: up-prod
up-prod: ## Start production stack
	$(DC_PROD) up -d

.PHONY: down-prod
down-prod: ## Stop production stack
	$(DC_PROD) down

.PHONY: logs-prod
logs-prod: ## Tail production logs
	$(DC_PROD) logs -f

# ── Docker: EC2 (lean — no Elasticsearch, no Langfuse) ───────────────────────

.PHONY: up-ec2
up-ec2: ## Start EC2 stack (no ES, no Langfuse)
	$(DC_EC2) up -d

.PHONY: down-ec2
down-ec2: ## Stop EC2 stack
	$(DC_EC2) down

.PHONY: logs-ec2
logs-ec2: ## Tail EC2 logs
	$(DC_EC2) logs -f

# ── Docker: Maintenance ──────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove stopped containers, dangling images
	docker system prune -f

.PHONY: clean-all
clean-all: ## Nuclear option — remove everything including volumes
	$(DC_LOCAL) down -v --remove-orphans
	docker system prune -af
	docker volume prune -f

.PHONY: db-shell
db-shell: ## Open psql in the database container
	$(DC_LOCAL) exec db psql -U $${POSTGRES_USER:-wanjala-art-sql-user} -d $${POSTGRES_DB:-wanjala-api-database}

db-up: ## Pull and start the Docker Postgres container in the background
	$(DC_LOCAL) up -d db

.PHONY: redis-cli
redis-cli: ## Open redis-cli in the redis container
	$(DC_LOCAL) exec redis redis-cli
