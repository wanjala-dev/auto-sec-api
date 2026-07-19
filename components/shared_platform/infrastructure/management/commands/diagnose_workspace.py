"""
Django management command to diagnose workspace content and embeddings
"""
from django.core.management.base import BaseCommand
from infrastructure.persistence.uploads.models import File
from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import create_elasticsearch_client, get_index_stats
import os

class Command(BaseCommand):
    help = 'Diagnose workspace content and embeddings'

    def add_arguments(self, parser):
        parser.add_argument('workspace_id', type=str, help='Workspace ID to diagnose')

    def handle(self, *args, **options):
        workspace_id = options['workspace_id']
        
        self.stdout.write(f"🔍 Diagnosing workspace content for: {workspace_id}")
        self.stdout.write("=" * 60)
        
        # Step 1: Check files associated with this workspace
        self.stdout.write("📋 Step 1: Checking files associated with this workspace...")
        try:
            files = File.objects.filter(workspace_id=workspace_id)
            self.stdout.write(self.style.SUCCESS(f"✅ Found {files.count()} files associated with workspace {workspace_id}"))
            
            if files.exists():
                self.stdout.write("📄 Files in this workspace:")
                for file in files:
                    self.stdout.write(f"   - ID: {file.id}, Type: {file.file_type}, Status: {file.processing_status}")
                    self.stdout.write(f"     Created: {file.created}, Processed: {file.processed_at}")
                    self.stdout.write(f"     Owner: {file.owner.id if file.owner else 'None'}")
                    self.stdout.write(f"     Path: {file.file.path}")
                    self.stdout.write(f"     Exists: {os.path.exists(file.file.path)}")
                    self.stdout.write("")
            else:
                self.stdout.write(self.style.WARNING("⚠️ No files found for this workspace. Continuing to check workspace embeddings."))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error checking files: {e}"))
            return
        
        # Step 2: Check Elasticsearch connection and index
        self.stdout.write("🔍 Step 2: Checking Elasticsearch...")
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
        
        # Step 3: Search for embeddings for this workspace
        self.stdout.write(f"\n🔍 Step 3: Searching for embeddings for workspace {workspace_id}...")
        try:
            # Search for documents with this workspace_id
            search_body = {
                "query": {
                    "term": {"metadata.workspace_id": workspace_id}
                },
                "_source": ["content", "metadata"],
                "size": 10
            }
            
            response = es_client.search(
                index='ai_documents',
                body=search_body
            )
            
            hits = response['hits']['hits']
            self.stdout.write(f"📊 Found {len(hits)} embeddings for workspace {workspace_id}")
            
            if hits:
                self.stdout.write(self.style.SUCCESS("✅ Workspace embeddings found in Elasticsearch:"))
                for i, hit in enumerate(hits[:3]):  # Show first 3
                    source = hit.get('_source', {})
                    metadata = source.get('metadata', {})
                    # Content field name can vary; try common options
                    raw_content = source.get('content') or source.get('text') or source.get('page_content') or ''
                    if isinstance(raw_content, str):
                        content_preview = raw_content[:100] + "..." if len(raw_content) > 100 else raw_content
                    else:
                        content_preview = ''
                    self.stdout.write(f"   Document {i+1}:")
                    self.stdout.write(f"     - PDF ID: {metadata.get('pdf_id')}")
                    self.stdout.write(f"     - Workspace ID: {metadata.get('workspace_id')}")
                    self.stdout.write(f"     - User ID: {metadata.get('user_id')}")
                    self.stdout.write(f"     - Type: {metadata.get('type')}")
                    if content_preview:
                        self.stdout.write(f"     - Content Preview: {content_preview}")
                    else:
                        self.stdout.write("     - Content Preview: <none>")
            else:
                self.stdout.write(self.style.ERROR("❌ No embeddings found for this workspace"))
                
                # Check if there are any documents with similar workspace_id
                self.stdout.write(f"\n🔍 Checking for similar workspace IDs...")
                search_body_similar = {
                    "query": {
                        "wildcard": {"metadata.workspace_id": f"*{workspace_id[-8:]}*"}
                    },
                    "_source": ["metadata"],
                    "size": 5
                }
                
                response_similar = es_client.search(
                    index='ai_documents',
                    body=search_body_similar
                )
                
                hits_similar = response_similar['hits']['hits']
                if hits_similar:
                    self.stdout.write(f"📊 Found {len(hits_similar)} documents with similar workspace IDs:")
                    for hit in hits_similar:
                        metadata = hit['_source']['metadata']
                        self.stdout.write(f"   - Workspace ID: {metadata.get('workspace_id')}")
                else:
                    self.stdout.write(self.style.ERROR("❌ No documents found with similar workspace IDs"))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Search failed: {e}"))
            return
        
        # Step 4: Check processing status of files
        self.stdout.write(f"\n🔍 Step 4: Checking file processing status...")
        try:
            pdf_files = files.filter(file_type='pdf')
            if pdf_files.exists():
                self.stdout.write(f"📄 PDF files in workspace:")
                for pdf_file in pdf_files:
                    self.stdout.write(f"   - ID: {pdf_file.id}, Status: {pdf_file.processing_status}")
                    if pdf_file.processing_status == 'failed':
                        self.stdout.write(f"     Error: {pdf_file.processing_error}")
                    elif pdf_file.processing_status == 'pending':
                        self.stdout.write(f"     ⚠️ This PDF needs processing")
                    elif pdf_file.processing_status == 'completed':
                        self.stdout.write(f"     ✅ This PDF should have embeddings")
            else:
                self.stdout.write(self.style.ERROR("❌ No PDF files found in this workspace"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error checking processing status: {e}"))
        
        # Recommendations
        self.stdout.write("\n💡 Recommendations:")
        if not hits:
            self.stdout.write("   1. No embeddings found - files may not be processed")
            self.stdout.write("   2. Check if PDF files have processing_status = 'completed'")
            self.stdout.write("   3. If files are pending/failed, reprocess them")
            self.stdout.write("   4. Verify the workspace_id is correct")
        else:
            self.stdout.write("   1. Embeddings exist - the issue might be with the search query")
            self.stdout.write("   2. Try different search terms")
            self.stdout.write("   3. Check if the user_id matches the embeddings")




















































