"""Delete the seeded ``*@test.octopi.dev`` persona test users.

These accounts existed solely to power the old DevPersonaSwitcher, which
swapped accounts via logout/login. The new switcher is a per-session
override on the real user's profile (``UserProfile.dev_persona_override``)
gated by the ``feature.dev_persona_switcher`` feature flag, so the
seeded users are no longer needed.

CASCADE deletes drop their related seeded data (teams they created,
projects, tasks, donations, sponsorships, etc.). Run on dev/local first
to confirm the blast radius is what you expect; run on prod to remove
the stale rows.

Usage:
    python manage.py cleanup_persona_test_users
    python manage.py cleanup_persona_test_users --dry-run
    python manage.py cleanup_persona_test_users --domain test.octopi.dev
"""

from __future__ import annotations

from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Delete seeded *@test.octopi.dev persona test users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default="test.octopi.dev",
            help="Email domain to target (default: test.octopi.dev).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print matching users without deleting.",
        )

    def handle(self, *args, **options):
        from infrastructure.persistence.users.models import CustomUser

        domain = options["domain"].strip().lower()
        if not domain:
            self.stderr.write(
                self.style.ERROR("--domain must be a non-empty string")
            )
            return

        suffix = f"@{domain}"
        qs = CustomUser.objects.filter(email__iendswith=suffix)
        users = list(qs)
        if not users:
            self.stdout.write(
                f"No users found matching {suffix} — nothing to do."
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {len(users)} user(s) matching {suffix}:"
            )
        )
        for user in users:
            self.stdout.write(f"  - id={user.id} email={user.email}")

        if options["dry_run"]:
            self.stdout.write(
                self.style.NOTICE("\nDry run — no deletes executed.")
            )
            return

        deleted_count, deleted_breakdown = self._force_delete(qs)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDeleted {deleted_count} row(s) total. Breakdown:"
            )
        )
        for model_label, n in sorted(deleted_breakdown.items()):
            self.stdout.write(f"  {model_label}: {n}")

    def _force_delete(self, queryset, _depth: int = 0):
        """Delete ``queryset``, recursively clearing PROTECT-ed referrers first.

        Several models deliberately PROTECT their referrers so real data can't
        be silently orphaned — a QA user owns a ``Workspace``
        (``workspace_owner`` is PROTECT), which in turn is referenced by
        ``PaymentAttempt``, ``AdminVerificationAuditLog``, etc. For a
        **test-data sweep** those protected rows are themselves test data, so we
        walk the chain: attempt the delete, and on ``ProtectedError`` delete the
        exact rows Django reports as blocking (recursively, since THEY may be
        protected too), then retry. This keeps the sweep robust as the schema
        grows new PROTECT edges — no per-model hard-coding, no residue that
        wedges the next QA run.

        Scoped to this command's domain-filtered test users; never call it on
        production data.
        """
        from django.db.models.deletion import ProtectedError

        aggregate: dict[str, int] = {}
        for _ in range(50):  # bounded — a real chain is only a few edges deep
            try:
                count, breakdown = queryset.delete()
            except ProtectedError as exc:
                by_model: dict[type, set] = {}
                for obj in exc.protected_objects:
                    by_model.setdefault(type(obj), set()).add(obj.pk)
                for model, pks in by_model.items():
                    _, sub = self._force_delete(
                        model._base_manager.filter(pk__in=pks), _depth + 1
                    )
                    for label, n in sub.items():
                        aggregate[label] = aggregate.get(label, 0) + n
                continue
            for label, n in breakdown.items():
                aggregate[label] = aggregate.get(label, 0) + n
            return sum(aggregate.values()), aggregate
        raise RuntimeError(
            "cleanup_persona_test_users: could not resolve protected deletes "
            "within the retry budget — the PROTECT chain is deeper than expected."
        )
