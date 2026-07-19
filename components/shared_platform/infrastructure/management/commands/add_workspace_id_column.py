from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Add workspace_id column to uploads_file table'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            try:
                # Check if column already exists
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'uploads_file' AND column_name = 'workspace_id'
                """)
                
                if cursor.fetchone():
                    self.stdout.write(
                        self.style.SUCCESS('Column workspace_id already exists')
                    )
                    return
                
                # Add the column
                cursor.execute("""
                    ALTER TABLE uploads_file 
                    ADD COLUMN workspace_id VARCHAR(36) NULL
                """)
                
                self.stdout.write(
                    self.style.SUCCESS('Successfully added workspace_id column to uploads_file table')
                )
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error adding column: {e}')
                )















