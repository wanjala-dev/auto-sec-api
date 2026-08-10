#!/bin/bash
set -o errexit
set -o nounset

# PROD ai_teammate-queue worker (deep-agent pipeline) — celery run DIRECTLY.
# The dev script wraps this in watchfiles (dev-only autoreloader); a prod image
# without watchfiles would CrashLoop on it, which is exactly the fork-drift the
# 2026-08-09 prod-readiness review flagged. Memory sizing rationale lives on the
# celery-ai-teammate-worker Deployment in auto-sec-infra.
: "${AI_TEAMMATE_CONCURRENCY:=2}"
: "${AI_TEAMMATE_PREFETCH:=1}"
: "${AI_TEAMMATE_MAX_TASKS_PER_CHILD:=25}"

exec celery -A api worker \
  -l "${CELERY_LOG_LEVEL:-INFO}" \
  -Q ai_teammate \
  --concurrency="${AI_TEAMMATE_CONCURRENCY}" \
  --prefetch-multiplier="${AI_TEAMMATE_PREFETCH}" \
  --max-tasks-per-child="${AI_TEAMMATE_MAX_TASKS_PER_CHILD}" \
  --hostname=ai-teammate@%h
