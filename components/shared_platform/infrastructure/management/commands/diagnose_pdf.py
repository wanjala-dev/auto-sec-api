"""
Django management command to diagnose PDF processing issues
"""
from django.core.management.base import BaseCommand
from infrastructure.persistence.uploads.models import File
from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import create_elasticsearch_client, get_index_stats
from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory
import os

class Command(BaseCommand):
    help = 'Diagnose PDF processing status and embeddings'

    def add_arguments(self, parser):
        parser.add_argument('pdf_id', type=int, help='PDF ID to diagnose')
        parser.add_argument('--workspace-id', type=str, help='Workspace ID to check')

    def handle(self, *args, **options):
        pdf_id = options['pdf_id']
        workspace_id = options.get('workspace_id')
        
        self.stdout.write(f"🔍 Diagnosing PDF {pdf_id}...")
        self.stdout.write("=" * 50)
        
        # Check database record
        try:
            file_record = File.objects.get(id=pdf_id)
            self.stdout.write(self.style.SUCCESS(f"✅ File record found:"))
            self.stdout.write(f"   - ID: {file_record.id}")
            self.stdout.write(f"   - File Type: {file_record.file_type}")
            self.stdout.write(f"   - Processing Status: {file_record.processing_status}")
            self.stdout.write(f"   - Workspace ID: {file_record.workspace_id}")
            self.stdout.write(f"   - Owner ID: {file_record.owner.id}")
            self.stdout.write(f"   - Created: {file_record.created}")
            self.stdout.write(f"   - Processed At: {file_record.processed_at}")
            self.stdout.write(f"   - Processing Error: {file_record.processing_error}")
            self.stdout.write(f"   - File Path: {file_record.file.path}")
            self.stdout.write(f"   - File Exists: {os.path.exists(file_record.file.path)}")
            
        except File.DoesNotExist:
            self.stdout.write(self.style.ERROR("❌ File record not found in database"))
            return
        
        # Check Elasticsearch connection and index
        self.stdout.write("\n🔍 Checking Elasticsearch...")
        try:
            es_client = create_elasticsearch_client()
            self.stdout.write(self.style.SUCCESS("✅ Elasticsearch connection successful"))
            
            # Check index stats
            index_stats = get_index_stats('ai_documents')
            if index_stats['index_exists']:
                self.stdout.write(self.style.SUCCESS(f"✅ Index exists with {index_stats['document_count']} documents"))
            else:
                self.stdout.write(self.style.ERROR("❌ Index does not exist"))
                return
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Elasticsearch connection failed: {e}"))
            return
        
        # Search for documents with PDF ID
        self.stdout.write(f"\n🔍 Searching for PDF {pdf_id} embeddings...")
        try:
            # Create embeddings instance
            embeddings = EmbeddingsFactory.create_embeddings(provider='openai')
            
            # Build search query
            must_conditions = [{"term": {"metadata.pdf_id": str(pdf_id)}}]
            
            if workspace_id:
                must_conditions.append({"term": {"metadata.workspace_id": workspace_id}})
            else:
                must_conditions.append({"term": {"metadata.workspace_id": str(file_record.workspace_id)}})
            
            must_conditions.append({"term": {"metadata.user_id": str(file_record.owner.id)}})
            
            # Search for documents with specific metadata
            search_body = {
                "query": {
                    "bool": {
                        "must": must_conditions
                    }
                },
                "_source": ["content", "metadata"],
                "size": 10
            }
            
            response = es_client.search(
                index='ai_documents',
                body=search_body
            )
            
            hits = response['hits']['hits']
            self.stdout.write(f"📊 Found {len(hits)} documents for PDF {pdf_id}")
            
            if hits:
                self.stdout.write(self.style.SUCCESS(f"✅ PDF {pdf_id} embeddings found in Elasticsearch:"))
                for i, hit in enumerate(hits[:3]):  # Show first 3
                    metadata = hit['_source']['metadata']
                    content_preview = hit['_source']['content'][:100] + "..." if len(hit['_source']['content']) > 100 else hit['_source']['content']
                    self.stdout.write(f"   Document {i+1}:")
                    self.stdout.write(f"     - PDF ID: {metadata.get('pdf_id')}")
                    self.stdout.write(f"     - Workspace ID: {metadata.get('workspace_id')}")
                    self.stdout.write(f"     - User ID: {metadata.get('user_id')}")
                    self.stdout.write(f"     - Type: {metadata.get('type')}")
                    self.stdout.write(f"     - Content Preview: {content_preview}")
            else:
                self.stdout.write(self.style.ERROR(f"❌ No embeddings found for PDF {pdf_id}"))
                
                # Check if there are any documents with PDF ID but different workspace/user
                self.stdout.write(f"\n🔍 Checking for PDF {pdf_id} with different metadata...")
                search_body_any = {
                    "query": {
                        "term": {"metadata.pdf_id": str(pdf_id)}
                    },
                    "_source": ["metadata"],
                    "size": 5
                }
                
                response_any = es_client.search(
                    index='ai_documents',
                    body=search_body_any
                )
                
                hits_any = response_any['hits']['hits']
                if hits_any:
                    self.stdout.write(f"📊 Found {len(hits_any)} documents with PDF ID {pdf_id} but different metadata:")
                    for hit in hits_any:
                        metadata = hit['_source']['metadata']
                        self.stdout.write(f"   - Workspace ID: {metadata.get('workspace_id')}, User ID: {metadata.get('user_id')}")
                else:
                    self.stdout.write(self.style.ERROR(f"❌ No documents found with PDF ID {pdf_id} at all"))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Search failed: {e}"))
        
        # Recommendations
        self.stdout.write("\n💡 Recommendations:")
        if file_record.processing_status != 'completed':
            self.stdout.write("   1. Re-process PDF - Status is not 'completed'")
        elif not hits:
            self.stdout.write("   1. Re-process PDF - No embeddings found despite completed status")
        else:
            self.stdout.write("   1. PDF appears to be processed correctly")




















































