#!/bin/bash
set -o errexit
set -o nounset

# Unified Celery worker that consumes ALL queues on a single process.
# Used by the EC2 lean stack to reduce memory footprint from 3 workers → 1.
#
# Concurrency is kept low (default 2) because AI tasks are I/O-bound
# (waiting on LLM APIs) and aggregations are sequential by nature.
# Lowered 3→2 on 2026-06-30 to free ~250MB on the RAM-tight t3a.medium demo
# (the web container needed more cgroup headroom to stop 502 OOM kills);
# override with UNIFIED_CONCURRENCY if a bigger host can afford more.

: "${UNIFIED_CONCURRENCY:=2}"
: "${UNIFIED_PREFETCH:=1}"
: "${UNIFIED_MAX_TASKS_PER_CHILD:=50}"

# Queue order matters: Celery prefetches from queues left-to-right, so list
# latency-sensitive queues first. `payments` must win over aggregations and
# AI work if the queue has anything waiting.
QUEUES="${CELERY_QUEUES_CSV:-payments,default,ai_teammate,workspace_aggregations}"

exec celery -A api worker \
  -l "${CELERY_LOG_LEVEL:-INFO}" \
  -Q "${QUEUES}" \
  --concurrency="${UNIFIED_CONCURRENCY}" \
  --prefetch-multiplier="${UNIFIED_PREFETCH}" \
  --max-tasks-per-child="${UNIFIED_MAX_TASKS_PER_CHILD}" \
  --hostname="unified@%h"
