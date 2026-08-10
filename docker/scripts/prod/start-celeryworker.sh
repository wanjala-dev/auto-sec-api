#!/bin/bash
set -o errexit
set -o nounset

# PROD default-queue worker — celery run DIRECTLY (no watchfiles: that wrapper
# is a dev-only autoreloader from requirements/development.txt; the prod image
# doesn't install it and the source is baked in, so there is nothing to watch).
# Flags mirror the k8s celery-worker Deployment (auto-sec-infra
# k8s/bases/celery/deployments.yaml): prefork pool, concurrency sized to the
# memory limit, prefetch 1 + max-tasks-per-child for lossless deploys.
exec celery -A api worker \
  -l "${CELERY_LOG_LEVEL:-INFO}" \
  --hostname=default@%h \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=50 \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-1}"
