# =============================================================================
# Multi-stage Dockerfile for the Auto-Sec API
#
# Stages:
#   base  — system deps, Python packages (shared by all targets)
#   dev   — development extras (git, gettext), dev requirements, startup scripts
#   prod  — THE canonical production image the k8s stack runs (gunicorn web,
#           direct celery workers — no watchfiles, no dev seeding, source baked
#           in and owned by the runtime uid). Built arm64 by auto-sec-infra's
#           `manage-prod.sh build-push` and pulled from ECR by the k3s node.
#
# Build targets:
#   docker build --target dev  -t auto-sec-backend:dev  -f docker/django/Dockerfile .
#   docker buildx build --platform linux/arm64 --target prod \
#     -t autosec-api:prod -f docker/django/Dockerfile .
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
    && ln -sf /scripts/celery/start-flower.sh /start-flower \
    && ln -sf /scripts/celery/start-cloud-posture.sh /start-celeryworker-cloud-posture

ENTRYPOINT ["/entrypoint"]

# ── Production stage ─────────────────────────────────────────────────────────
# Fixes the 2026-08-09 prod-readiness review's blocker #4 — the previous prod
# stage was wanjala fork-drift that could not run under the k8s manifests:
#   - no /start symlink (the api Deployment's command) → api CrashLooped;
#   - /start-celeryworker* wrapped celery in `watchfiles`, a development.txt-only
#     autoreloader → workers CrashLooped in a prod image;
#   - /app was root-owned → celery-beat's PersistentScheduler couldn't write its
#     schedule file;
#   - it pip-uninstalled langfuse, which base.txt pins at 3.x for the agent
#     tracing that IS a product feature (the rest of that uninstall list was an
#     EC2-image slimming hack; the unused packages are inert — prod settings
#     strip their Django apps — so the whole error-prone step is dropped).
FROM base AS prod

COPY ./requirements /requirements
RUN pip install --no-cache-dir -r /requirements/production.txt

# Application code, then scripts (both from the clean `git archive` context).
COPY . .
COPY ./docker/scripts/ /scripts/
RUN find /scripts/ -type f -exec sed -i 's/\r$//' {} \; \
    && find /scripts/ -type f -exec chmod +x {} \;

# The /start* contract the k8s manifests call — pointed at docker/scripts/prod/
# (gunicorn web; DIRECT celery, no watchfiles; beat state in /tmp). The dev
# wrappers stay in the image only as /scripts/… — nothing links to them.
RUN ln -sf /scripts/entrypoint.sh /entrypoint \
    && ln -sf /scripts/prod/start-web.sh /start \
    && ln -sf /scripts/prod/start-celeryworker.sh /start-celeryworker \
    && ln -sf /scripts/prod/start-ai-teammate.sh /start-celeryworker-ai-teammate \
    && ln -sf /scripts/prod/start-scanning-worker.sh /start-scanning-worker \
    && ln -sf /scripts/prod/start-beat.sh /start-celerybeat

# The k8s stack runs every container as uid 1000 (runAsNonRoot). /app must be
# owned by it: collectstatic writes STATIC_ROOT here, and Django's tempfile
# usage expects a writable workdir. Same fix local-image.Dockerfile carries.
RUN chown -R 1000:1000 /app
USER 1000

EXPOSE 8000

ENTRYPOINT ["/entrypoint"]
CMD ["/start"]
