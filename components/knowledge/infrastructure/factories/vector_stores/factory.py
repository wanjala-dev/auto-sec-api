"""
Vector Stores Factory - Central factory for creating different vector store providers.

The default provider is read from ``settings.VECTOR_STORE_PROVIDER`` so prod
(lean stack, no Elasticsearch) defaults to pgvector and dev can opt back into
Elasticsearch by flipping a single env var. Call sites no longer hardcode the
provider — they call ``create_vector_store(**kwargs)`` and trust the factory
to pick the configured backend.
"""

from django.conf import settings


def _resolve_default_provider() -> str:
    """Read the configured default vector store provider.

    Falls back to ``pgvector`` because the lean stack (prod) doesn't ship
    elasticsearch. Pinning the default to pgvector here means any caller
    that omits ``provider=`` lands on the available backend rather than
    crashing with ``No module named 'elasticsearch'`` the way the
    2026-05-27 demo import did.
    """
    return getattr(settings, "VECTOR_STORE_PROVIDER", "pgvector")


class VectorStoreFactory:
    """Factory class for creating different vector store providers"""

    PROVIDERS = {
        'elasticsearch': {
            'vector_store': 'build_elasticsearch_vector_store',
            'retriever': 'build_elasticsearch_retriever'
        },
        'pgvector': {
            'vector_store': 'build_pgvector_store',
            'retriever': 'build_pgvector_retriever'
        },
    }

    @classmethod
    def create_vector_store(cls, provider=None, **kwargs):
        """
        Create a vector store instance based on provider

        Args:
            provider: Vector store provider name. When None (default), reads
                ``settings.VECTOR_STORE_PROVIDER`` so callers don't have to
                know which backend is wired up in the running environment.
            **kwargs: Additional arguments for the vector store

        Returns:
            Vector store instance
        """
        if provider is None:
            provider = _resolve_default_provider()
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Available: {list(cls.PROVIDERS.keys())}")

        try:
            if provider == 'elasticsearch':
                from .elasticsearch import build_elasticsearch_vector_store
                return build_elasticsearch_vector_store(**kwargs)
            elif provider == 'pgvector':
                from .pgvector import build_pgvector_store
                return build_pgvector_store(**kwargs)
            else:
                raise ValueError(f"Unknown provider: {provider}")

        except Exception as e:
            raise ValueError(f"Vector store provider '{provider}' is not available: {str(e)}")

    @classmethod
    def create_retriever(cls, provider=None, chat_args=None, **kwargs):
        """
        Create a retriever instance based on provider

        Args:
            provider: Vector store provider name. When None (default), reads
                ``settings.VECTOR_STORE_PROVIDER``.
            chat_args: Chat configuration object
            **kwargs: Additional arguments for the retriever

        Returns:
            Retriever instance
        """
        if provider is None:
            provider = _resolve_default_provider()
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Available: {list(cls.PROVIDERS.keys())}")

        try:
            if provider == 'elasticsearch':
                from .elasticsearch import build_elasticsearch_retriever
                return build_elasticsearch_retriever(chat_args=chat_args, **kwargs)
            elif provider == 'pgvector':
                from .pgvector import build_pgvector_retriever
                return build_pgvector_retriever(chat_args=chat_args, **kwargs)
            else:
                raise ValueError(f"Unknown provider: {provider}")

        except Exception as e:
            raise ValueError(f"Vector store provider '{provider}' is not available: {str(e)}")
    
    @classmethod
    def get_available_providers(cls):
        """Get list of available providers"""
        return list(cls.PROVIDERS.keys())
    
    @classmethod
    def get_provider_info(cls, provider):
        """Get information about a specific provider"""
        if provider not in cls.PROVIDERS:
            return None
        
        return {
            'provider': provider,
            'supports_retrieval': 'retriever' in cls.PROVIDERS[provider],
            'required_env_vars': cls._get_required_env_vars(provider)
        }
    
    @classmethod
    def _get_required_env_vars(cls, provider):
        """Get required environment variables for a provider"""
        env_vars = {
            'elasticsearch': ['ELASTICSEARCH_URL', 'ELASTICSEARCH_INDEX_NAME'],
            'pgvector': ['DATABASE_URL'],
        }
        return env_vars.get(provider, [])
