"""Coerce drifted WorkspaceMembership.role values to valid RBAC roles.

``WorkspaceMembership.role`` must be one of the four RBAC tiers
(owner / admin / member / viewer); ``sponsor`` is a *persona*, not a role
(ADR 0002). Some rows drifted to ``role='sponsor'`` — an invalid role that
leaves the membership without a proper RBAC tier. Sponsors are read-only,
so they map to ``viewer`` (persona stays ``sponsor``).

This command coerces ``role='sponsor'`` → ``role='viewer'`` and *reports*
any other out-of-vocabulary role values it finds without changing them, so
unanalysed drift surfaces for a follow-up rather than being silently
remapped. Idempotent.

Usage:
    python manage.py backfill_membership_roles
    python manage.py backfill_membership_roles --dry-run
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.core.management import BaseCommand


# The only valid RBAC role tiers (WorkspaceMembership.Role).
_VALID_ROLES = {"owner", "admin", "member", "viewer"}

# Documented, safe coercions for invalid roles that are actually persona
# values. Sponsors are read-only → viewer. Add more only after analysing
# the RBAC implications of each.
_SAFE_COERCIONS = {"sponsor": "viewer"}


class Command(BaseCommand):
    help = "Coerce drifted WorkspaceMembership.role values to valid RBAC roles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        WorkspaceMembership = django_apps.get_model(
            "workspaces", "WorkspaceMembership"
        )

        total_fixed = 0
        for bad_role, good_role in _SAFE_COERCIONS.items():
            qs = WorkspaceMembership.objects.filter(role=bad_role)
            count = qs.count()
            if not count:
                self.stdout.write(f"  role='{bad_role}': none found")
                continue
            self.stdout.write(
                self.style.WARNING(
                    f"  role='{bad_role}' → '{good_role}': {count} row(s)"
                )
            )
            if not dry_run:
                qs.update(role=good_role)
            total_fixed += count

        # Surface (but do NOT touch) any other invalid role values.
        other_invalid = (
            WorkspaceMembership.objects.exclude(role__in=_VALID_ROLES)
            .exclude(role__in=_SAFE_COERCIONS.keys())
            .values_list("role", flat=True)
            .distinct()
        )
        other_invalid = sorted({r for r in other_invalid if r})
        if other_invalid:
            self.stdout.write(
                self.style.ERROR(
                    "  Unhandled invalid role values found (left unchanged — "
                    f"needs analysis): {', '.join(other_invalid)}"
                )
            )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    f"\nDRY RUN — would coerce {total_fixed} membership row(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCoerced {total_fixed} membership row(s) to valid roles."
                )
            )
