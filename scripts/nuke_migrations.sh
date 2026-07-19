#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/nuke_migrations.sh [--sudo] [--dry-run]

Deletes Django migration files in this repo while explicitly avoiding virtualenvs.

This removes:
  - */migrations/*.py (except __init__.py)
  - */migrations/*.pyc

Safety:
  - Prunes common generated dirs (venv/.venv/.git/static/media/logs/etc.)
EOF
}

sudo_prefix=()
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sudo)
      sudo_prefix=(sudo)
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
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

if [[ ! -f manage.py ]]; then
  echo "Expected to run from the Django project root (manage.py not found)." >&2
  exit 2
fi

find_cmd=(
  "${sudo_prefix[@]}"
  find .
  -type d
  \\(
    -name .git
    -o -name venv
    -o -name .venv
    -o -name .venv-deps-check
    -o -name .venv-deps-check-311
    -o -name media
    -o -name test-media
    -o -name static
    -o -name static-test
    -o -name logs
    -o -name .pytest_cache
    -o -name .pytest-dbs
  \\)
  -prune
  -o
  -type f
  \\(
    -path "*/migrations/*.py"
    -o -path "*/migrations/*.pyc"
  \\)
  ! -name "__init__.py"
  -print
)

if [[ "${dry_run}" == "true" ]]; then
  "${find_cmd[@]}"
  exit 0
fi

"${find_cmd[@]}" -delete
