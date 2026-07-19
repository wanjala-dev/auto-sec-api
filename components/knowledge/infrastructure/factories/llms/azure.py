"""
Azure OpenAI Chat Model Factory
"""
import os

try:
    from langchain_openai import AzureChatOpenAI  # type: ignore
except ImportError:  # pragma: no cover - fallback
    from langchain_community.chat_models import AzureChatOpenAI  # type: ignore


def build_azure_llm(chat_args=None, model_name="gpt-35-turbo", **kwargs):
    """
    Build Azure OpenAI ChatOpenAI instance with configuration
    
    Args:
        chat_args: Chat configuration object (optional)
        model_name: Model name to use
        **kwargs: Additional arguments for AzureChatOpenAI
    
    Returns:
        AzureChatOpenAI instance
    """
    # Default configuration
    config = {
        "openai_api_key": os.environ.get('AZURE_OPENAI_API_KEY'),
        "openai_api_base": os.environ.get('AZURE_OPENAI_API_BASE'),
        "openai_api_version": os.environ.get('AZURE_OPENAI_API_VERSION', "2023-05-15"),
        "deployment_name": os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME', model_name),
        "model_name": model_name,
        "temperature": 0.7,
        "max_tokens": 1000,
        "streaming": False,
    }
    
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
        if hasattr(chat_args, 'deployment_name'):
            config['deployment_name'] = chat_args.deployment_name
    
    # Override with any additional kwargs
    config.update(kwargs)
    
    return AzureChatOpenAI(**config)


def build_azure_streaming_llm(chat_args=None, model_name="gpt-35-turbo", **kwargs):
    """
    Build streaming Azure OpenAI ChatOpenAI instance
    
    Args:
        chat_args: Chat configuration object (optional)
        model_name: Model name to use
        **kwargs: Additional arguments for AzureChatOpenAI
    
    Returns:
        Streaming AzureChatOpenAI instance
    """
    config = {
        "streaming": True,
        "callbacks": kwargs.get('callbacks', [])
    }
    
    return build_azure_llm(chat_args, model_name, **config)

































