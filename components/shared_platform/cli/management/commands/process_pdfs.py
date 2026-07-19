"""
Management command to process PDF files and generate embeddings
"""
from django.core.management.base import BaseCommand, CommandError
from infrastructure.persistence.uploads.models import File
from infrastructure.persistence.uploads.tasks import process_pdf_file, process_pending_pdfs


class Command(BaseCommand):
    help = 'Process PDF files and generate embeddings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file-id',
            type=int,
            help='Process a specific PDF file by ID'
        )
        parser.add_argument(
            '--all-pending',
            action='store_true',
            help='Process all pending PDF files'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Run processing asynchronously via Celery'
        )

    def handle(self, *args, **options):
        if options['file_id']:
            self.process_single_file(options['file_id'], options['async'])
        elif options['all_pending']:
            self.process_all_pending(options['async'])
        else:
            self.show_status()

    def process_single_file(self, file_id, async_mode):
        """Process a single PDF file"""
        try:
            file_instance = File.objects.get(id=file_id)
            
            if not file_instance.is_pdf:
                raise CommandError(f"File {file_id} is not a PDF file")
            
            self.stdout.write(f"Processing PDF file: {file_instance.file.name}")
            
            if async_mode:
                # Run asynchronously
                task = process_pdf_file.delay(file_id)
                self.stdout.write(
                    self.style.SUCCESS(f"Started async processing task: {task.id}")
                )
            else:
                # Run synchronously
                result = process_pdf_file(file_id)
                if result['success']:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully processed PDF. "
                            f"Created {result['chunks_created']} embeddings, "
                            f"extracted {result['text_length']} characters from {result['page_count']} pages"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"Failed to process PDF: {result['error']}")
                    )
                    
        except File.DoesNotExist:
            raise CommandError(f"File with ID {file_id} not found")
        except Exception as e:
            raise CommandError(f"Error processing file: {str(e)}")

    def process_all_pending(self, async_mode):
        """Process all pending PDF files"""
        pending_pdfs = File.objects.filter(
            file_type='pdf',
            processing_status__in=['pending', 'failed']
        )
        
        if not pending_pdfs.exists():
            self.stdout.write(self.style.WARNING("No pending PDF files found"))
            return
        
        self.stdout.write(f"Found {pending_pdfs.count()} pending PDF files")
        
        if async_mode:
            # Run asynchronously
            result = process_pending_pdfs.delay()
            self.stdout.write(
                self.style.SUCCESS(f"Started async processing for all pending PDFs: {result.id}")
            )
        else:
            # Run synchronously
            processed_count = 0
            for pdf_file in pending_pdfs:
                self.stdout.write(f"Processing: {pdf_file.file.name}")
                result = process_pdf_file(pdf_file.id)
                if result['success']:
                    processed_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ Processed {pdf_file.file.name}")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"✗ Failed {pdf_file.file.name}: {result['error']}")
                    )
            
            self.stdout.write(
                self.style.SUCCESS(f"Processed {processed_count}/{pending_pdfs.count()} PDF files")
            )

    def show_status(self):
        """Show status of PDF files"""
        total_pdfs = File.objects.filter(file_type='pdf').count()
        pending_pdfs = File.objects.filter(file_type='pdf', processing_status='pending').count()
        processing_pdfs = File.objects.filter(file_type='pdf', processing_status='processing').count()
        completed_pdfs = File.objects.filter(file_type='pdf', processing_status='completed').count()
        failed_pdfs = File.objects.filter(file_type='pdf', processing_status='failed').count()
        
        self.stdout.write("PDF Processing Status:")
        self.stdout.write(f"  Total PDFs: {total_pdfs}")
        self.stdout.write(f"  Pending: {pending_pdfs}")
        self.stdout.write(f"  Processing: {processing_pdfs}")
        self.stdout.write(f"  Completed: {completed_pdfs}")
        self.stdout.write(f"  Failed: {failed_pdfs}")
        
        if failed_pdfs > 0:
            self.stdout.write("\nFailed PDFs:")
            for pdf in File.objects.filter(file_type='pdf', processing_status='failed'):
                self.stdout.write(f"  - {pdf.file.name} (ID: {pdf.id})")
                if pdf.processing_error:
                    self.stdout.write(f"    Error: {pdf.processing_error}")

