#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/reset_db_and_migrate.sh [--sudo] [--web-container NAME]

Destructive local workflow:
  1) Delete migration files (excluding venv/.venv)
  2) docker-compose down -v
  3) Clear __pycache__ (excluding venv/.venv)
  4) docker-compose up -d
  5) makemigrations + migrate inside the web container
EOF
}

sudo_flag=""
web_container="api-v20-web-1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sudo)
      sudo_flag="--sudo"
      shift
      ;;
    --web-container)
      web_container="${2:-}"
      if [[ -z "${web_container}" ]]; then
        echo "--web-container requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f docker-compose.yml ]]; then
  echo "docker-compose.yml not found; run from the project root." >&2
  exit 2
fi
if [[ ! -f manage.py ]]; then
  echo "manage.py not found; run from the project root." >&2
  exit 2
fi

compose_cmd=(docker-compose)
if ! command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker compose)
fi

echo "==> Deleting migration files"
./scripts/nuke_migrations.sh ${sudo_flag}

echo "==> Dropping docker volumes"
"${compose_cmd[@]}" down -v

echo "==> Clearing __pycache__ (excluding virtualenvs)"
find . \
  -type d \( -name .git -o -name venv -o -name .venv -o -name media -o -name test-media -o -name static -o -name static-test -o -name logs \) \
  -prune -o \
  -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "==> Starting stack"
"${compose_cmd[@]}" up -d

echo "==> Recreating schema inside ${web_container}"
# DB_USE_DIRECT=1 bypasses PgBouncer for schema work (db:5432, session mode).
docker exec -it -e DB_USE_DIRECT=1 "${web_container}" python manage.py makemigrations
docker exec -it -e DB_USE_DIRECT=1 "${web_container}" python manage.py migrate
