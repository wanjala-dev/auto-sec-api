"""
Elasticsearch Vector Store - Direct integration with proper dense_vector mapping
Based on best practices from: https://medium.com/@vishalpaalakurthi/vector-embedding-in-elasticsearch-simplified-guide-e35186fdf83e
"""
import os
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_community.vectorstores import ElasticsearchStore
from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory


def create_elasticsearch_client():
    """Create Elasticsearch client with proper configuration"""
    es_url = os.environ.get('ELASTICSEARCH_URL', 'http://elasticsearch:9200')
    es_user = os.environ.get('ELASTICSEARCH_USER', 'elastic')
    es_password = os.environ.get('ELASTICSEARCH_PASSWORD', 'hygWoV1g25n04LtOu6Q44o58')
    
    return Elasticsearch(
        [es_url],
        basic_auth=(es_user, es_password),
        verify_certs=False,
        request_timeout=30
    )


def create_vector_index_mapping(index_name, embedding_dimension=1536):
    """
    Create proper index mapping for vector embeddings
    Based on Elasticsearch dense_vector best practices
    """
    mapping = {
        "mappings": {
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "standard"
                },
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dimension,
                    "index": True,
                    "similarity": "cosine"
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "keyword"},
                        "pdf_id": {"type": "keyword"},
                        "user_id": {"type": "keyword"},
                        "workspace_id": {"type": "keyword"},
                        "workspace_name": {"type": "text"},
                        "owner_id": {"type": "keyword"},
                        "created_at": {"type": "date"},
                        "privacy": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "source": {"type": "keyword"}
                    }
                }
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0
        }
    }
    return mapping


def build_elasticsearch_vector_store(
    index_name=None, 
    embeddings_instance=None,
    embedding_dimension=1536
):
    """
    Build improved Elasticsearch vector store with proper dense_vector mapping
    
    Args:
        index_name: Elasticsearch index name
        embeddings_instance: Embeddings instance
        embedding_dimension: Dimension of the embedding vectors
    
    Returns:
        ElasticsearchStore instance
    """
    # Use provided parameters or fall back to defaults
    if not index_name:
        index_name = os.environ.get('ELASTICSEARCH_INDEX_NAME', 'ai_documents')
    
    if not embeddings_instance:
        embeddings_instance = EmbeddingsFactory.create_embeddings(provider='openai')
    
    # Get Elasticsearch URL from environment or use default
    es_url = os.environ.get('ELASTICSEARCH_URL', 'http://elasticsearch:9200')
    es_user = os.environ.get('ELASTICSEARCH_USER', 'elastic')
    es_password = os.environ.get('ELASTICSEARCH_PASSWORD', 'hygWoV1g25n04LtOu6Q44o58')
    
    # Create Elasticsearch client
    es_client = create_elasticsearch_client()
    
    # Check if index exists, create with proper mapping if not
    if not es_client.indices.exists(index=index_name):
        print(f"Creating index {index_name} with proper vector mapping...")
        mapping = create_vector_index_mapping(index_name, embedding_dimension)
        es_client.indices.create(index=index_name, body=mapping)
        print(f"✅ Index {index_name} created successfully")
    
    # Build connection parameters for ElasticsearchStore
    connection_params = {
        'es_url': es_url,
        'es_user': es_user,
        'es_password': es_password
    }
    
    return ElasticsearchStore(
        index_name=index_name,
        embedding=embeddings_instance,
        vector_query_field="embedding",
        **connection_params
    )


def build_elasticsearch_retriever(chat_args, k=4, vector_store=None, embeddings_instance=None):
    """
    Build retriever from Elasticsearch vector store
    
    Args:
        chat_args: Chat configuration object
        k: Number of documents to retrieve
        vector_store: Vector store instance
    
    Returns:
        Retriever instance
    """
    if not vector_store:
        vector_store = build_elasticsearch_vector_store(embeddings_instance=embeddings_instance)

    # Build optional metadata filter for Elasticsearch
    es_filter = None
    try:
        must_clauses = []
        # Support simple attribute object (e.g., type('ChatArgs', (), {...})())
        pdf_id = getattr(chat_args, 'pdf_id', None)
        workspace_id = getattr(chat_args, 'workspace_id', None)
        user_id = getattr(chat_args, 'user_id', None)

        if pdf_id:
            must_clauses.append({"term": {"metadata.pdf_id": str(pdf_id)}})
        if workspace_id:
            must_clauses.append({"term": {"metadata.workspace_id": str(workspace_id)}})
        if user_id:
            must_clauses.append({"term": {"metadata.user_id": str(user_id)}})

        if must_clauses:
            es_filter = {"bool": {"must": must_clauses}}
    except Exception:
        # If anything goes wrong building the filter, proceed without it
        es_filter = None

    search_kwargs = {"k": k}
    if es_filter:
        # LangChain's ElasticsearchStore accepts a 'filter' key in search_kwargs
        search_kwargs["filter"] = es_filter

    return vector_store.as_retriever(search_kwargs=search_kwargs)


def test_vector_search(index_name='ai_documents', query_text="test document", k=5):
    """
    Test vector search functionality directly with Elasticsearch
    
    Args:
        index_name: Elasticsearch index name
        query_text: Text to search for
        k: Number of results to return
    
    Returns:
        Search results
    """
    es_client = create_elasticsearch_client()
    embeddings = EmbeddingsFactory.create_embeddings(provider='openai')
    
    # Generate embedding for query
    query_embedding = embeddings.embed_query(query_text)
    
    # Perform vector search
    search_body = {
        "knn": {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": k,
            "num_candidates": k * 2
        },
        "_source": ["content", "metadata"]
    }
    
    response = es_client.search(
        index=index_name,
        body=search_body
    )
    
    return response['hits']['hits']


def get_index_stats(index_name='ai_documents'):
    """Get statistics about the vector index"""
    es_client = create_elasticsearch_client()
    
    try:
        stats = es_client.indices.stats(index=index_name)
        mapping = es_client.indices.get_mapping(index=index_name)
        
        return {
            'index_exists': True,
            'document_count': stats['indices'][index_name]['total']['docs']['count'],
            'index_size': stats['indices'][index_name]['total']['store']['size_in_bytes'],
            'mapping': mapping[index_name]['mappings']
        }
    except Exception as e:
        return {
            'index_exists': False,
            'error': str(e)
        }
