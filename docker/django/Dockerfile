# =============================================================================
# Multi-stage Dockerfile for Wanjala API
#
# Stages:
#   base  — system deps, Python packages (shared by all targets)
#   dev   — development extras (git, gettext), dev requirements, startup scripts
#   prod  — production-only requirements, gunicorn, no dev tooling
#
# Build targets:
#   docker build --target dev  -t wanjala-api:dev  -f docker/django/Dockerfile .
#   docker build --target prod -t wanjala-api:prod -f docker/django/Dockerfile .
# =============================================================================

# ── Base stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOME=/app

WORKDIR $APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

# Install torch CPU-only BEFORE the main requirements.  sentence-transformers
# is a transitive dep needed for the cross-encoder reranker (Tier 3 #10);
# without this pin pip would resolve to the GPU torch which pulls ~10GB of
# NVIDIA CUDA libraries we have no use for on our CPU-only EC2 instances.
# Pinning here means downstream `pip install` finds torch already present
# and skips the heavier resolution.
# See docs/plans/RAG_EVAL_BASELINE.md "cross-encoder reranker" follow-up.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch

# ── Development stage ────────────────────────────────────────────────────────
FROM base AS dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gettext \
        git \
        gcc \
        libc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements /requirements
RUN pip install --no-cache-dir -r /requirements/development.txt

# Copy all startup scripts and fix line endings in one layer
COPY ./docker/scripts/ /scripts/
RUN find /scripts/ -type f -exec sed -i 's/\r$//' {} \; \
    && find /scripts/ -type f -exec chmod +x {} \;

# Symlink scripts to / for backward compat with docker-compose commands
RUN ln -sf /scripts/entrypoint.sh /entrypoint \
    && ln -sf /scripts/start-web.sh /start \
    && ln -sf /scripts/celery/start-worker.sh /start-celeryworker \
    && ln -sf /scripts/celery/start-ai-teammate.sh /start-celeryworker-ai-teammate \
    && ln -sf /scripts/celery/start-aggregations.sh /start-celeryworker-aggregations \
    && ln -sf /scripts/celery/start-worker-unified.sh /start-celeryworker-unified \
    && ln -sf /scripts/celery/start-beat.sh /start-celerybeat \
    && ln -sf /scripts/celery/start-flower.sh /start-flower

ENTRYPOINT ["/entrypoint"]

# ── Production stage ─────────────────────────────────────────────────────────
FROM base AS prod

COPY ./requirements /requirements
# NOTE: install and uninstall are SEPARATE steps on purpose. The old
# `pip install … && pip uninstall … || true` let the `|| true` (meant for the
# uninstall) swallow a pip-install FAILURE — producing a "successful" image
# with no dependencies installed (caught 2026-07-19 building the 1.x image).
RUN pip install --no-cache-dir -r /requirements/production.txt
RUN pip uninstall -y \
        django-elasticsearch-dsl elasticsearch elasticsearch-dsl \
        elastic-apm elastic-transport \
        langfuse \
        django-haystack pysolr \
        Faker django-seed \
    2>/dev/null || true

# Copy application code
COPY . .

# Copy startup scripts
COPY ./docker/scripts/ /scripts/
RUN find /scripts/ -type f -exec sed -i 's/\r$//' {} \; \
    && find /scripts/ -type f -exec chmod +x {} \;

RUN ln -sf /scripts/entrypoint.sh /entrypoint \
    && ln -sf /scripts/celery/start-worker.sh /start-celeryworker \
    && ln -sf /scripts/celery/start-ai-teammate.sh /start-celeryworker-ai-teammate \
    && ln -sf /scripts/celery/start-aggregations.sh /start-celeryworker-aggregations \
    && ln -sf /scripts/celery/start-worker-unified.sh /start-celeryworker-unified \
    && ln -sf /scripts/celery/start-beat.sh /start-celerybeat

EXPOSE 8000

ENTRYPOINT ["/entrypoint"]
CMD ["gunicorn", "--bind", ":8000", "--workers", "3", "api.wsgi"]
