#!/bin/bash
set -o errexit
set -o pipefail
set -o nounset

# ── Wait for PostgreSQL ──────────────────────────────────────────────────────
#
# Uses DATABASE_URL if available (standard), otherwise falls back to
# individual DEFAULT_* vars for backward compatibility.

postgres_ready() {
python << END
import sys
import os

try:
    import psycopg2
except ImportError:
    # psycopg2 not installed — skip readiness check
    sys.exit(0)

database_url = os.environ.get("DATABASE_URL", "")

if database_url:
    try:
        conn = psycopg2.connect(database_url)
        conn.close()
    except psycopg2.OperationalError as exc:
        print(f"PostgreSQL not ready (DATABASE_URL): {exc}", file=sys.stderr)
        sys.exit(-1)
else:
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get("POSTGRES_DB", "wanjala-api-database"),
            user=os.environ.get("POSTGRES_USER", "wanjala-art-sql-user"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            host=os.environ.get("POSTGRES_HOST", "db"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
        )
        conn.close()
    except psycopg2.OperationalError as exc:
        print(f"PostgreSQL not ready: {exc}", file=sys.stderr)
        sys.exit(-1)

sys.exit(0)
END
}

until postgres_ready; do
    >&2 echo 'Waiting for PostgreSQL to become available...'
    sleep 2
done
>&2 echo 'PostgreSQL is available.'

# ── Auto-configure Django Site from env vars ────────────────────────────────
# Only runs for web/gunicorn processes (not celery workers/beat or daphne).
# The previous pattern ``*start*`` accidentally matched every celery wrapper
# script (/start-celerybeat, /start-celeryworker*) and made beat hang for
# minutes on cold boot, running three sequential ``manage.py`` invocations
# it didn't need. Match only the web command shapes:
#   - ``gunicorn ...``       (production web in docker-compose.ec2.yml)
#   - ``/start`` / ``/start-web*``  (dev wrapper symlink → start-web.sh)
case "${1:-}" in
  gunicorn*|/start|/start-web*)
    if python manage.py configure_site 2>/dev/null; then
      >&2 echo 'Django Site configured from environment.'
    fi
    if python manage.py seed_payment_providers 2>/dev/null; then
      >&2 echo 'Payment providers seeded.'
    fi
    if python manage.py seed_feature_flags 2>/dev/null; then
      >&2 echo 'Feature flags seeded.'
    fi
    ;;
esac

exec "$@"
