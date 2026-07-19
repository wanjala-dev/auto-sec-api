#!/bin/bash
set -o errexit
set -o pipefail
set -o nounset

# Schema work bypasses PgBouncer (DB_USE_DIRECT=1 → db:5432 in settings). DDL +
# migration-history repair want a dedicated session-mode connection, not a
# multiplexed transaction-mode pooled one. Runtime serving below stays pooled.
DB_USE_DIRECT=1 python manage.py repair_migration_history --database=default --yes
DB_USE_DIRECT=1 python manage.py makemigrations --noinput
DB_USE_DIRECT=1 python manage.py migrate

# SaaS billing: seed subscription tiers (pricing plans) so orgs have plans to
# attach. Idempotent. `|| true` swallows the "already seeded" case.
python manage.py seed_subscription_tiers || true

# octopus-security fork: the nonprofit `bootstrap_dev` (personas + subscription
# tiers + workspace defaults) is retired. For now we create a minimal superuser
# so the admin/API is reachable. A security-appropriate dev-seed command will
# replace this in the bootstrapping pass.
#   Idempotent: `|| true` swallows the "user already exists" case only.
DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-admin}" \
DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-admin@octopus.local}" \
DJANGO_SUPERUSER_PASSWORD="${SUPER_USER_PASSWORD:-octopus-admin-local}" \
  python manage.py createsuperuser --noinput || true

# Identity blocks login on unverified email (login_use_case: `if not
# user.is_verified`). createsuperuser leaves is_verified=False, so the freshly
# seeded admin can't actually log in. Mark every superuser verified + onboarded
# so the admin is login-ready on first boot (idempotent).
python manage.py shell -c "
from infrastructure.persistence.users.models import CustomUser
for u in CustomUser.objects.filter(is_superuser=True):
    changed = False
    if not u.is_verified:
        u.is_verified = True; changed = True
    if hasattr(u, 'is_onboard_complete') and not u.is_onboard_complete:
        u.is_onboard_complete = True; changed = True
    if changed:
        u.save()
" || true

python manage.py runserver 0.0.0.0:8000
