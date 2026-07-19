from django.core.management.base import CommandError, BaseCommand
from infrastructure.persistence.utils.workspace_data import workspace_data

class Command(BaseCommand):
    help = "Populate the database with test data."

    def handle(self, *args, **options):
        workspace_data()
        self.stdout.write(self.style.SUCCESS('Successfully seeded database with test data.'))
