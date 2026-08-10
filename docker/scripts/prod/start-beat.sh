#!/bin/bash
set -o errexit
set -o nounset

# PROD beat — schedule + pidfile pinned to /tmp so the scheduler works even if
# /app is read-only (the k8s celery-beat Deployment mounts an emptyDir at /tmp).
# The dev script writes ./celerybeat-schedule into the cwd, which required the
# image to chown /app; keeping beat's writable state in /tmp removes that
# coupling entirely.
rm -f /tmp/celerybeat.pid
exec celery -A api beat \
  -l "${CELERY_LOG_LEVEL:-INFO}" \
  --schedule=/tmp/celerybeat-schedule \
  --pidfile=/tmp/celerybeat.pid
