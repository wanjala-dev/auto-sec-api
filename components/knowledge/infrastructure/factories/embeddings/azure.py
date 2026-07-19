"""
Azure OpenAI Embeddings Factory
"""
import os

try:
    from langchain_openai import OpenAIEmbeddings  # preferred (avoids deprecation warnings)
except ImportError:  # pragma: no cover
    from langchain_community.embeddings import OpenAIEmbeddings


def build_azure_embeddings(model_name="text-embedding-ada-002", **kwargs):
    """
    Build Azure OpenAI embeddings instance
    
    Args:
        model_name: Embedding model name
        **kwargs: Additional arguments for OpenAIEmbeddings
    
    Returns:
        OpenAIEmbeddings instance configured for Azure
    """
    config = {
        "openai_api_key": os.environ.get('AZURE_OPENAI_API_KEY'),
        "openai_api_base": os.environ.get('AZURE_OPENAI_API_BASE'),
        "openai_api_version": os.environ.get('AZURE_OPENAI_API_VERSION', "2023-05-15"),
        "openai_api_type": "azure",  # This is crucial for Azure OpenAI
        "deployment": os.environ.get('AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME', model_name),
        "model": model_name,
        "chunk_size": 1000,
    }
    
    # Override with any additional kwargs
    config.update(kwargs)
    
    return OpenAIEmbeddings(**config)
