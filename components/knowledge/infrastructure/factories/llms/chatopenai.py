"""
OpenAI Chat Model Factory
"""
# DEPRECATION: ChatOpenAI moved to langchain_openai package.
import os
from typing import Optional

# Note: Langfuse tracing is handled via CallbackHandler in the agent executor
# The OpenAI wrapper (langfuse.openai) requires OpenAI SDK v1.0+, but we're using LangChain
# which may use an older version. The CallbackHandler approach works with all OpenAI SDK versions.

try:
    from langchain_openai import ChatOpenAI  # type: ignore
except ImportError:  # pragma: no cover - fallback for older deployments
    from langchain_community.chat_models import ChatOpenAI  # type: ignore


def build_llm(chat_args=None, model_name="gpt-3.5-turbo", **kwargs):
    """
    Build OpenAI ChatOpenAI instance with configuration
    
    Args:
        chat_args: Chat configuration object (optional)
        model_name: Model name to use
        **kwargs: Additional arguments for ChatOpenAI
    
    Returns:
        ChatOpenAI instance
    """
    request_timeout = _read_env_float("OPENAI_REQUEST_TIMEOUT")
    max_retries = _read_env_int("OPENAI_MAX_RETRIES")

    # Default configuration. request_timeout is ALWAYS set so we never
    # inherit the OpenAI SDK's ~600s default — a hung request on a Celery
    # worker holds the slot open for ten minutes and amplifies retry
    # storms (celery-tasks skill §3). 60s is a generous ceiling for a
    # single chat completion; override via OPENAI_REQUEST_TIMEOUT.
    config = {
        "openai_api_key": os.environ.get('OPENAI_API_KEY'),
        "model_name": model_name,
        "temperature": 0.7,
        "max_tokens": 1000,
        "streaming": False,
        "request_timeout": request_timeout if request_timeout is not None else 60.0,
    }
    if max_retries is not None:
        config["max_retries"] = max_retries
    
    # Override with chat_args if provided
    if chat_args:
        if hasattr(chat_args, 'streaming'):
            config['streaming'] = chat_args.streaming
        if hasattr(chat_args, 'temperature'):
            config['temperature'] = chat_args.temperature
        if hasattr(chat_args, 'max_tokens'):
            config['max_tokens'] = chat_args.max_tokens
        if hasattr(chat_args, 'model_name'):
            config['model_name'] = chat_args.model_name
    
    # Override with any additional kwargs
    config.update(kwargs)
    
    return ChatOpenAI(**config)


def _read_env_float(name: str) -> Optional[float]:
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


def _read_env_int(name: str) -> Optional[int]:
    """Return an environment variable as int, or None when unset/invalid."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def build_streaming_llm(chat_args=None, model_name="gpt-3.5-turbo", **kwargs):
    """
    Build streaming OpenAI ChatOpenAI instance
    
    Args:
        chat_args: Chat configuration object (optional)
        model_name: Model name to use
        **kwargs: Additional arguments for ChatOpenAI
    
    Returns:
        Streaming ChatOpenAI instance
    """
    config = {
        "streaming": True,
        "callbacks": kwargs.get('callbacks', [])
    }
    
    return build_llm(chat_args, model_name, **config)





























