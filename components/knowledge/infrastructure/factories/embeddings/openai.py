"""
OpenAI Embeddings Factory
"""
import os

try:
    from langchain_openai import OpenAIEmbeddings  # preferred (avoids deprecation warnings)
except ImportError:  # pragma: no cover - fallback for older deployments
    from langchain_community.embeddings import OpenAIEmbeddings


class LazyEmbeddingsProxy:
    """Lazily constructs embeddings to keep app startup lightweight."""

    def __init__(self, builder):
        self._builder = builder
        self._instance = None

    def _get(self):
        if self._instance is None:
            self._instance = self._builder()
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get(), name)


def build_embeddings(model_name="text-embedding-ada-002", **kwargs):
    """
    Build OpenAI embeddings instance
    
    Args:
        model_name: Embedding model name
        **kwargs: Additional arguments for OpenAIEmbeddings
    
    Returns:
        OpenAIEmbeddings instance
    """
    # request_timeout is set explicitly so we never inherit the OpenAI
    # SDK's ~600s default — a hung embeddings request on a Celery worker
    # holds the slot open for ten minutes and amplifies retry storms
    # (celery-tasks skill §3). 30s is a generous ceiling for an embeddings
    # batch; override via OPENAI_REQUEST_TIMEOUT env or kwargs.
    request_timeout = _read_env_float("OPENAI_REQUEST_TIMEOUT")
    config = {
        "openai_api_key": os.environ.get('OPENAI_API_KEY'),
        "model": model_name,
        "chunk_size": 1000,
        "request_timeout": request_timeout if request_timeout is not None else 30.0,
    }

    # Override with any additional kwargs (e.g. an explicit request_timeout)
    config.update(kwargs)

    return OpenAIEmbeddings(**config)


def _read_env_float(name: str):
    """Return an environment variable as float, or None when unset/invalid."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# Lazily-initialized embeddings instance for easy access
embeddings = LazyEmbeddingsProxy(build_embeddings)
