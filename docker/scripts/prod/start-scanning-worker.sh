#!/bin/bash
set -o errexit
set -o nounset

# PROD scanning worker — all three scan-pillar queues (cloud_posture,
# container_security, code_security), celery run DIRECTLY (no watchfiles).
# Mirrors the k8s scanning-worker Deployment: one prefork child, prefetch 1 —
# scans are heavy, long-running K8s Jobs held open by the task, so cluster-wide
# scan serialization is deliberate at this scale.
: "${SCANNING_CONCURRENCY:=1}"
: "${SCANNING_PREFETCH:=1}"
: "${SCANNING_MAX_TASKS_PER_CHILD:=10}"

exec celery -A api worker \
  -l "${CELERY_LOG_LEVEL:-INFO}" \
  -Q cloud_posture,container_security,code_security \
  --concurrency="${SCANNING_CONCURRENCY}" \
  --prefetch-multiplier="${SCANNING_PREFETCH}" \
  --max-tasks-per-child="${SCANNING_MAX_TASKS_PER_CHILD}" \
  --hostname=scanning@%h
