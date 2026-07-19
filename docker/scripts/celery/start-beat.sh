#!/bin/bash
set -o errexit
set -o nounset

rm -f './celerybeat.pid'
exec celery -A api beat -l "${CELERY_LOG_LEVEL:-INFO}"
