#!/bin/bash
set -o errexit
set -o nounset

# Dedicated cloud-posture worker — runs the Prowler CSPM scan tasks
# (cloud_posture queue). Low concurrency: a scan is heavy + long-running.
: "${CLOUD_POSTURE_CONCURRENCY:=1}"
: "${CLOUD_POSTURE_PREFETCH:=1}"
: "${CLOUD_POSTURE_MAX_TASKS_PER_CHILD:=10}"

watchfiles \
  --filter python \
  "celery -A api worker -l ${CELERY_LOG_LEVEL:-INFO} -Q cloud_posture --concurrency=${CLOUD_POSTURE_CONCURRENCY} --prefetch-multiplier=${CLOUD_POSTURE_PREFETCH} --max-tasks-per-child=${CLOUD_POSTURE_MAX_TASKS_PER_CHILD} --hostname=cloud-posture@%h"
