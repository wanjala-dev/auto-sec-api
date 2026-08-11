from django.core.management.commands.migrate import Command as MigrationCommand

from django.db import connection
from ...utils import get_tenants_map


class Command(MigrationCommand):
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            schemas = get_tenants_map().values()
            for schema in schemas:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", [schema])
                cursor.execute("SET search_path to %s", [schema])
                super(Command, self).handle(*args, **options)
