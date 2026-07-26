from django.core.management.base import BaseCommand
from components.knowledge.application.providers.content_embedding_provider import (
    get_content_embedding_provider,
)


class Command(BaseCommand):
    help = 'Create embeddings for workspace content'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all content (not just recent)',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run as Celery task (asynchronous)',
        )

    def handle(self, *args, **options):
        if options['all']:
            if options['async']:
                self.stdout.write('Starting full embeddings task asynchronously...')
                task = get_content_embedding_provider().enqueue_all_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task started with ID: {task.id}')
                )
            else:
                self.stdout.write('Starting full embeddings task...')
                result = get_content_embedding_provider().run_all_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task completed: {result}')
                )
        else:
            if options['async']:
                self.stdout.write('Starting daily embeddings task asynchronously...')
                task = get_content_embedding_provider().enqueue_recent_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task started with ID: {task.id}')
                )
            else:
                self.stdout.write('Starting daily embeddings task...')
                result = get_content_embedding_provider().run_recent_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task completed: {result}')
                )
