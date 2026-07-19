"""
Embeddings Factory - Central factory for creating different embedding providers
"""
import os
from .openai import build_embeddings as build_openai_embeddings
from .azure import build_azure_embeddings

# Make Elasticsearch native embeddings optional
try:
    from .elasticsearch_native import build_elasticsearch_native_embeddings
    ELASTICSEARCH_NATIVE_IMPORTED = True
    print("DEBUG: Elasticsearch native embeddings module import OK")
except ImportError as e:
    ELASTICSEARCH_NATIVE_IMPORTED = False
    build_elasticsearch_native_embeddings = None
    print(f"DEBUG: Elasticsearch native embeddings not importable: {e}")


class EmbeddingsFactory:
    """Factory class for creating different embedding providers"""
    
    @classmethod
    def _get_providers(cls):
        """Get available providers dynamically"""
        providers = {
            'openai': build_openai_embeddings,
            'azure': build_azure_embeddings,
        }
        
        # Add Elasticsearch native if available
        # Gate ES-native by env to avoid confusion in production
        if ELASTICSEARCH_NATIVE_IMPORTED and os.environ.get('ENABLE_ES_NATIVE_EMBEDDINGS', 'false').lower() in ('1', 'true', 'yes'):
            providers['elasticsearch_native'] = build_elasticsearch_native_embeddings
            print("DEBUG: Added Elasticsearch native to providers (env-enabled)")
        else:
            print("DEBUG: Elasticsearch native disabled (set ENABLE_ES_NATIVE_EMBEDDINGS=true to enable)")
            
        return providers
    
    @classmethod
    def create_embeddings(cls, provider='openai', **kwargs):
        """
        Create an embeddings instance based on provider
        
        Args:
            provider: Embedding provider ('openai', 'azure', 'huggingface' if available)
            **kwargs: Additional arguments for the embeddings
        
        Returns:
            Embeddings instance
        """
        providers = cls._get_providers()
        if provider not in providers:
            raise ValueError(f"Unsupported provider: {provider}. Available: {list(providers.keys())}")
        
        builder_func = providers[provider]
        return builder_func(**kwargs)
    
    @classmethod
    def get_available_providers(cls):
        """Get list of available providers"""
        providers = cls._get_providers()
        print(f"DEBUG: Factory providers: {list(providers.keys())}")
        return list(providers.keys())
    
    @classmethod
    def get_provider_info(cls, provider):
        """Get information about a specific provider"""
        providers = cls._get_providers()
        if provider not in providers:
            return None
        
        return {
            'provider': provider,
            'available_models': cls._get_available_models(provider)
        }
    
    @classmethod
    def _get_available_models(cls, provider):
        """Get available models for a provider"""
        models = {
            'openai': ['text-embedding-ada-002', 'text-embedding-3-small', 'text-embedding-3-large'],
            'azure': ['text-embedding-ada-002', 'text-embedding-3-small', 'text-embedding-3-large'],
        }
        return models.get(provider, [])
