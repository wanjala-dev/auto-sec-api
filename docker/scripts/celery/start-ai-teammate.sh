#!/bin/bash
set -o errexit
set -o nounset

: "${AI_TEAMMATE_CONCURRENCY:=2}"
: "${AI_TEAMMATE_PREFETCH:=1}"
: "${AI_TEAMMATE_MAX_TASKS_PER_CHILD:=25}"

watchfiles \
  --filter python \
  "celery -A api worker -l ${CELERY_LOG_LEVEL:-INFO} -Q ai_teammate --concurrency=${AI_TEAMMATE_CONCURRENCY} --prefetch-multiplier=${AI_TEAMMATE_PREFETCH} --max-tasks-per-child=${AI_TEAMMATE_MAX_TASKS_PER_CHILD} --hostname=ai-teammate@%h"
