"""
Django management command to reprocess all files in a workspace
"""
from django.core.management.base import BaseCommand
from infrastructure.persistence.uploads.models import File
from infrastructure.persistence.uploads.tasks import process_pdf_file
from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import create_elasticsearch_client
import os

class Command(BaseCommand):
    help = 'Reprocess all files in a workspace'

    def add_arguments(self, parser):
        parser.add_argument('workspace_id', type=str, help='Workspace ID to reprocess')
        parser.add_argument('--force', action='store_true', help='Force reprocessing even if already completed')

    def handle(self, *args, **options):
        workspace_id = options['workspace_id']
        force = options.get('force', False)
        
        self.stdout.write(f"🔄 Reprocessing all files in workspace {workspace_id}...")
        self.stdout.write("=" * 60)
        
        try:
            files = File.objects.filter(workspace_id=workspace_id)
            self.stdout.write(f"📋 Found {files.count()} files in workspace {workspace_id}")
            
            if not files.exists():
                self.stdout.write(self.style.ERROR("❌ No files found for this workspace"))
                return
            
            pdf_files = files.filter(file_type='pdf')
            self.stdout.write(f"📄 Found {pdf_files.count()} PDF files")
            
            if not pdf_files.exists():
                self.stdout.write(self.style.WARNING("⚠️ No PDF files found in this workspace"))
                return
            
            # Clear existing embeddings for this workspace
            self.stdout.write("\n🧹 Clearing existing embeddings for this workspace...")
            try:
                es_client = create_elasticsearch_client()
                
                # Delete existing documents for this workspace
                delete_query = {
                    "query": {
                        "term": {"metadata.workspace_id": workspace_id}
                    }
                }
                
                response = es_client.delete_by_query(
                    index='ai_documents',
                    body=delete_query
                )
                
                deleted_count = response.get('deleted', 0)
                self.stdout.write(f"✅ Deleted {deleted_count} existing embeddings")
                
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"⚠️ Could not clear existing embeddings: {e}"))
            
            # Process each PDF file
            self.stdout.write("\n🚀 Starting PDF processing tasks...")
            task_results = []
            
            for pdf_file in pdf_files:
                self.stdout.write(f"\n📄 Processing PDF {pdf_file.id}...")
                self.stdout.write(f"   - File: {pdf_file.file.name}")
                self.stdout.write(f"   - Current Status: {pdf_file.processing_status}")
                self.stdout.write(f"   - File Exists: {os.path.exists(pdf_file.file.path)}")
                
                if pdf_file.processing_status == 'completed' and not force:
                    self.stdout.write(self.style.WARNING("   ⚠️ PDF is already processed. Use --force to reprocess"))
                    continue
                
                if not os.path.exists(pdf_file.file.path):
                    self.stdout.write(self.style.ERROR("   ❌ PDF file does not exist on disk"))
                    continue
                
                # Reset file status
                pdf_file.processing_status = 'pending'
                pdf_file.processing_error = None
                pdf_file.processed_at = None
                pdf_file.save()
                self.stdout.write("   ✅ File status reset to pending")
                
                # Start processing task
                try:
                    result = process_pdf_file.delay(pdf_file.id)
                    task_results.append({
                        'file_id': pdf_file.id,
                        'task_id': result.id,
                        'status': 'started'
                    })
                    self.stdout.write(f"   ✅ Processing task started with ID: {result.id}")
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"   ❌ Failed to start processing task: {e}"))
                    task_results.append({
                        'file_id': pdf_file.id,
                        'task_id': None,
                        'status': 'failed',
                        'error': str(e)
                    })
            
            # Summary
            self.stdout.write("\n📊 Processing Summary:")
            self.stdout.write(f"   - Total PDF files: {pdf_files.count()}")
            self.stdout.write(f"   - Tasks started: {len([r for r in task_results if r['status'] == 'started'])}")
            self.stdout.write(f"   - Tasks failed: {len([r for r in task_results if r['status'] == 'failed'])}")
            
            if task_results:
                self.stdout.write("\n📋 Task Details:")
                for result in task_results:
                    if result['status'] == 'started':
                        self.stdout.write(f"   - File {result['file_id']}: Task {result['task_id']}")
                    else:
                        self.stdout.write(f"   - File {result['file_id']}: Failed - {result.get('error', 'Unknown error')}")
            
            self.stdout.write("\n💡 Next steps:")
            self.stdout.write("   1. Wait for processing to complete")
            self.stdout.write("   2. Check file processing_status fields")
            self.stdout.write("   3. Run diagnose_workspace command to verify embeddings")
            self.stdout.write("   4. Try accessing workspace content again")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error reprocessing workspace: {e}"))



















































