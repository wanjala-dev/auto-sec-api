"""Ensure payment webhook endpoints exist for active payment methods."""
from django.conf import settings
from django.core.management import BaseCommand, CommandError

from infrastructure.persistence.workspaces.payments.models import PaymentWebhookEndpoint, WorkspacePaymentMethod


class Command(BaseCommand):
    help = (
        "Ensure PaymentWebhookEndpoint rows exist for active payment methods. "
        "Use --update-existing to sync URL/secret/status for existing rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            default="donations",
            help="Logical webhook name to ensure (default: donations).",
        )
        parser.add_argument(
            "--url",
            default=None,
            help="Webhook URL to store. If omitted, uses settings.DONATIONS_WEBHOOK_URL.",
        )
        parser.add_argument(
            "--secret",
            default=None,
            help=(
                "Webhook signing secret. Defaults to STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET, "
                "then STRIPE_CONNECT_WEBHOOK_SECRET, then STRIPE_WEBHOOK_KEY."
            ),
        )
        parser.add_argument(
            "--provider",
            default="stripe",
            help="Provider slug prefix to match (default: stripe).",
        )
        parser.add_argument(
            "--status",
            default=PaymentWebhookEndpoint.STATUS_ACTIVE,
            choices=[choice[0] for choice in PaymentWebhookEndpoint.STATUS_CHOICES],
            help="Status to set on created/updated webhooks.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to use (default: default).",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help=(
                "Update URL/secret/status for existing webhook rows. Rows whose "
                "secret was captured from the provider (provider_endpoint_id set) "
                "keep their signing_secret unless --force-secret is also passed."
            ),
        )
        parser.add_argument(
            "--force-secret",
            action="store_true",
            help=(
                "With --update-existing: overwrite signing_secret even on rows "
                "whose secret was captured from the provider at registration "
                "(provider_endpoint_id set). Overwriting such a row breaks "
                "signature verification for that endpoint's deliveries — only "
                "use it after the provider-side endpoint has been replaced."
            ),
        )
        parser.add_argument(
            "--include-missing-account",
            action="store_true",
            help="Include methods without provider_account_id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show actions without writing changes.",
        )

    def handle(self, *args, **options):
        name = options["name"]
        db_alias = options["database"]
        provider_prefix = options["provider"]
        status = options["status"]
        update_existing = options["update_existing"]
        force_secret = options["force_secret"]
        include_missing_account = options["include_missing_account"]
        dry_run = options["dry_run"]

        url = options["url"] or getattr(settings, "DONATIONS_WEBHOOK_URL", "")
        secret = options["secret"] or getattr(
            settings, "STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET", ""
        )
        if not secret:
            secret = getattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", "")
        if not secret:
            secret = getattr(settings, "STRIPE_WEBHOOK_KEY", "")

        if not url:
            raise CommandError(
                "Missing webhook URL. Pass --url or set DONATIONS_WEBHOOK_URL in settings."
            )
        if not secret:
            raise CommandError(
                "Missing webhook secret. Pass --secret or set STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET."
            )

        methods = (
            WorkspacePaymentMethod.objects.using(db_alias)
            .select_related("workspace", "provider")
            .filter(
                provider__slug__startswith=provider_prefix,
                status=WorkspacePaymentMethod.STATUS_ACTIVE,
                is_deleted=False,
            )
        )
        if not include_missing_account:
            methods = methods.filter(provider_account_id__gt="")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for method in methods:
            existing = (
                PaymentWebhookEndpoint.objects.using(db_alias)
                .filter(method=method, name=name)
                .first()
            )
            if existing:
                updates = []
                if update_existing:
                    if existing.url != url:
                        existing.url = url
                        updates.append("url")
                    if existing.signing_secret != secret:
                        # A row with provider_endpoint_id carries a secret
                        # captured from the provider at registration — it is
                        # the ONLY copy (providers never return it again).
                        # Overwriting it with the env secret breaks signature
                        # verification for that endpoint's deliveries (the
                        # 2026-07-04 webhook-403 incident). Require an
                        # explicit --force-secret to do that.
                        if existing.provider_endpoint_id and not force_secret:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Skipping secret overwrite for webhook id={existing.pk} "
                                    f"(provider_endpoint_id={existing.provider_endpoint_id}); "
                                    "pass --force-secret to override."
                                )
                            )
                        else:
                            existing.signing_secret = secret
                            updates.append("signing_secret")
                            if force_secret and existing.provider_endpoint_id:
                                # The captured secret is gone; the row is now
                                # env-managed. Clearing the id keeps the
                                # "non-empty means endpoint-specific secret"
                                # invariant true.
                                existing.provider_endpoint_id = ""
                                updates.append("provider_endpoint_id")
                    if existing.status != status:
                        existing.status = status
                        updates.append("status")
                if updates:
                    updated_count += 1
                    if not dry_run:
                        existing.save(update_fields=updates + ["updated_at"])
                else:
                    skipped_count += 1
                continue

            created_count += 1
            if dry_run:
                continue
            PaymentWebhookEndpoint.objects.using(db_alias).create(
                method=method,
                name=name,
                url=url,
                signing_secret=secret,
                status=status,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Webhook endpoints ensured for '{name}': "
                f"created={created_count}, updated={updated_count}, skipped={skipped_count}."
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run enabled; no changes were saved."))
