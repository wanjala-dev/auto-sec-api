from django.core.management.base import BaseCommand
from components.knowledge.infrastructure.tasks.embedding_tasks import create_embeddings_for_workspace_content, create_embeddings_for_all_content


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
                task = create_embeddings_for_all_content.delay()
                self.stdout.write(
                    self.style.SUCCESS(f'Task started with ID: {task.id}')
                )
            else:
                self.stdout.write('Starting full embeddings task...')
                result = create_embeddings_for_all_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task completed: {result}')
                )
        else:
            if options['async']:
                self.stdout.write('Starting daily embeddings task asynchronously...')
                task = create_embeddings_for_workspace_content.delay()
                self.stdout.write(
                    self.style.SUCCESS(f'Task started with ID: {task.id}')
                )
            else:
                self.stdout.write('Starting daily embeddings task...')
                result = create_embeddings_for_workspace_content()
                self.stdout.write(
                    self.style.SUCCESS(f'Task completed: {result}')
                )
