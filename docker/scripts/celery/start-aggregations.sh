#!/bin/bash
set -o errexit
set -o nounset

: "${AGGREGATIONS_CONCURRENCY:=1}"
: "${AGGREGATIONS_PREFETCH:=1}"
: "${AGGREGATIONS_MAX_TASKS_PER_CHILD:=50}"

watchfiles \
  --filter python \
  "celery -A api worker -l ${CELERY_LOG_LEVEL:-INFO} -Q seed_aggregations --concurrency=${AGGREGATIONS_CONCURRENCY} --prefetch-multiplier=${AGGREGATIONS_PREFETCH} --max-tasks-per-child=${AGGREGATIONS_MAX_TASKS_PER_CHILD} --hostname=aggregations@%h"
