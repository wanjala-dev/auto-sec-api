"""
Elasticsearch Native Embeddings - Use Elasticsearch's built-in text embedding
"""
import os
from typing import List, Optional
from langchain_community.embeddings import ElasticsearchEmbeddings


def build_elasticsearch_native_embeddings(**kwargs):
    """
    Build Elasticsearch native embeddings instance
    
    Args:
        **kwargs: Additional arguments for the embeddings
    
    Returns:
        ElasticsearchEmbeddings instance
    """
    # Get Elasticsearch configuration from environment
    es_url = os.environ.get('ELASTICSEARCH_URL', 'http://elasticsearch:9200')
    es_user = os.environ.get('ELASTICSEARCH_USER', 'elastic')
    es_password = os.environ.get('ELASTICSEARCH_PASSWORD', 'hygWoV1g25n04LtOu6Q44o58')
    
    # Create Elasticsearch native embeddings
    embeddings = ElasticsearchEmbeddings(
        es_cloud_id=None,  # Not using cloud
        es_api_key=None,   # Not using API key
        es_connection={
            "host": es_url,
            "port": 9200,
            "scheme": "http",
            "username": es_user,
            "password": es_password,
            "verify_certs": False,
            "request_timeout": 30
        },
        **kwargs
    )
    
    return embeddings


