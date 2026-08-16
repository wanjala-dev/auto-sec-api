"""Frozen corpus source — the dogfood shape behind findings 9976/9977 (#866/#869)."""

from app.tenants import get_tenants_map
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            schemas = get_tenants_map().values()
            for schema in schemas:
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                cursor.execute(f"SET search_path to {schema}")
                self.run_schema_migrations(cursor)

    def run_schema_migrations(self, cursor):
        cursor.execute("SELECT 1")
