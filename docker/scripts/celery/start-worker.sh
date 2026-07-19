#!/bin/bash
set -o errexit
set -o nounset

# --prefetch-multiplier=1 + --max-tasks-per-child=50 are defense-in-depth for
# lossless deploys. They mirror the CELERY_WORKER_* values in api/settings/prod.py
# so the contract holds even if env doesn't pick up the setting (Celery applies
# the lower of CLI vs settings). See celery-tasks skill rule 5.
watchfiles \
  --filter python \
  "celery -A api worker -l ${CELERY_LOG_LEVEL:-INFO} --hostname=default@%h --prefetch-multiplier=1 --max-tasks-per-child=50"
