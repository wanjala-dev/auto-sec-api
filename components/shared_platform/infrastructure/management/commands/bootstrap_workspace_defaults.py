"""Management command to provision baseline reference data for workspaces."""
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = (
        "Ensure baseline reference data exists: workspace & campaign categories, "
        "budget categories, contribution means, subscription plans."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Ensuring workspace categories exist"))
        call_command('populate_workspace_categories')

        self.stdout.write(self.style.NOTICE("Ensuring contribution means exist"))
        call_command('populate_contribution_means')

        self.stdout.write(self.style.NOTICE("Ensuring subscription plans exist"))
        # Single source of truth — delegate to the canonical tier seeder
        # instead of duplicating the Free/Pro/Premium definition here.
        call_command('seed_subscription_tiers')

        self.stdout.write(self.style.NOTICE("Ensuring campaign categories exist"))
        call_command('seed_campaign_categories')

        self.stdout.write(self.style.NOTICE("Seeding budget categories for all workspaces"))
        call_command('workspace_categories', all=True)

        self.stdout.write(self.style.SUCCESS("Workspace defaults are ready."))
