from django.core.management.base import BaseCommand
from infrastructure.persistence.uploads.models import File
from components.knowledge.infrastructure.adapters.pdf_embeddings import create_embeddings_for_pdf
from components.knowledge.infrastructure.adapters.document_embeddings import create_embeddings_for_document
from django.utils import timezone


class Command(BaseCommand):
    help = 'Reprocess a specific document (PDF, docx, csv, xls/xlsx) to create embeddings'

    def add_arguments(self, parser):
        parser.add_argument('pdf_id', type=int, help='ID of the document file to reprocess')
        parser.add_argument('--workspace-id', type=str, help='Workspace ID (optional)')

    def handle(self, *args, **options):
        pdf_id = options['pdf_id']
        workspace_id = options.get('workspace_id')

        try:
            # Get the file
            file_obj = File.objects.get(id=pdf_id)
            
            if file_obj.file_type not in ('pdf', 'document'):
                self.stdout.write(
                    self.style.ERROR(f"File {pdf_id} is not a supported document type")
                )
                return

            self.stdout.write(f"Reprocessing document file: {file_obj.file.name}")
            
            # Use the workspace_id from the file if not provided
            if not workspace_id:
                workspace_id = file_obj.workspace_id
                
            if not workspace_id:
                self.stdout.write(
                    self.style.ERROR(f"No workspace_id found for file {pdf_id}")
                )
                return

            # Call the embeddings function directly
            if file_obj.is_pdf:
                embeddings_result = create_embeddings_for_pdf(
                    pdf_id=str(pdf_id),
                    pdf_path=file_obj.file.path,
                    user_id=str(file_obj.owner.id) if file_obj.owner else None,
                    workspace_id=str(workspace_id)
                )
            else:
                embeddings_result = create_embeddings_for_document(
                    file_id=str(pdf_id),
                    file_path=file_obj.file.path,
                    user_id=str(file_obj.owner.id) if file_obj.owner else None,
                    workspace_id=str(workspace_id)
                )
            
            if embeddings_result['success']:
                # Update file status
                file_obj.processing_status = 'completed'
                file_obj.processed_at = timezone.now()
                file_obj.processing_error = None
                file_obj.save()
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully reprocessed document {pdf_id}. "
                        f"Created {embeddings_result['chunks_created']} chunks, "
                        f"generated {embeddings_result['embeddings_generated']} embeddings"
                    )
                )
            else:
                # Update file status with error
                file_obj.processing_status = 'failed'
                file_obj.processing_error = embeddings_result.get('error', 'Unknown error')
                file_obj.save()
                
                self.stdout.write(
                    self.style.ERROR(f"Failed to reprocess document: {embeddings_result.get('error', 'Unknown error')}")
                )
                
        except File.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"File with ID {pdf_id} not found")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error reprocessing file: {str(e)}")
            )











































