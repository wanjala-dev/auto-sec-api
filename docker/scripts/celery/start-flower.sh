#!/bin/bash
set -o errexit
set -o nounset

worker_ready() {
    celery -A api inspect ping
}

until worker_ready; do
    >&2 echo 'Celery workers not available'
    sleep 1
done
>&2 echo 'Celery workers available'

exec celery -A api \
    --broker="${CELERY_BROKER}" \
    flower \
    --basic-auth="${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-changeme}"
