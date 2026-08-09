#!/bin/bash
set -o errexit
set -o pipefail
set -o nounset

# PROD web entrypoint — gunicorn only. Deliberately NOT start-web.sh (the dev
# wrapper): no makemigrations, no demo seeding, no superuser creation, no
# runserver. Schema changes run as the k8s migrate Job (k8s/bases/migration in
# auto-sec-infra) BEFORE the rollout; the first admin is created manually via
# `kubectl exec … createsuperuser` in an SSM session. A prod web pod's only job
# is to serve.

# collectstatic is cheap (seconds) and idempotent; STATIC_ROOT lives in /app
# (chowned to the runtime uid in the prod image stage). WhiteNoise serves the
# result — there is no nginx sidecar in the k8s stack.
python manage.py collectstatic --noinput

exec gunicorn api.wsgi \
  --bind "0.0.0.0:${GUNICORN_PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-100}" \
  --access-logfile - \
  --error-logfile -
