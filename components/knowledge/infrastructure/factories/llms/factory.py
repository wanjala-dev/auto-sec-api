"""
LLM Factory - Central factory for creating different LLM providers
"""
import os
from .chatopenai import build_llm as build_openai_llm, build_streaming_llm as build_openai_streaming_llm
from .azure import build_azure_llm, build_azure_streaming_llm
from .chatanthropic import build_llm as build_anthropic_llm, build_streaming_llm as build_anthropic_streaming_llm


class LLMFactory:
    """Factory class for creating different LLM providers"""

    PROVIDERS = {
        'openai': {
            'llm': build_openai_llm,
            'streaming': build_openai_streaming_llm
        },
        'azure': {
            'llm': build_azure_llm,
            'streaming': build_azure_streaming_llm
        },
        # Wave 4 of the prompt-evaluation plan — unlocks
        # PlannerJudge(model_name="claude-...", provider="anthropic")
        # so cross-vendor grading (OpenAI-as-judge vs Claude-as-judge)
        # is one CLI flag, not a rewrite of the harness.
        'anthropic': {
            'llm': build_anthropic_llm,
            'streaming': build_anthropic_streaming_llm,
        },
    }
    
    @classmethod
    def create_llm(cls, provider='openai', streaming=False, chat_args=None, **kwargs):
        """
        Create an LLM instance based on provider
        
        Args:
            provider: LLM provider ('openai', 'azure')
            streaming: Whether to create streaming LLM
            chat_args: Chat configuration object
            **kwargs: Additional arguments for the LLM
        
        Returns:
            LLM instance
        """
        if provider not in cls.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Available: {list(cls.PROVIDERS.keys())}")
        
        llm_type = 'streaming' if streaming else 'llm'
        builder_func = cls.PROVIDERS[provider][llm_type]
        
        return builder_func(chat_args=chat_args, **kwargs)

    @classmethod
    def get_llm(cls, model_name=None, provider=None, streaming=False, chat_args=None, **kwargs):
        """
        Backward-compatible helper to create an LLM instance.

        Defaults to Azure when Azure OpenAI env vars are present; otherwise uses OpenAI.
        """
        resolved_provider = provider
        if resolved_provider is None:
            has_azure = bool(
                os.environ.get("AZURE_OPENAI_API_KEY")
                and os.environ.get("AZURE_OPENAI_API_BASE")
            )
            resolved_provider = "azure" if has_azure else "openai"
        if model_name:
            kwargs.setdefault("model_name", model_name)
        return cls.create_llm(
            provider=resolved_provider,
            streaming=streaming,
            chat_args=chat_args,
            **kwargs,
        )
    
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
            'supports_streaming': 'streaming' in cls.PROVIDERS[provider],
            'available_models': cls._get_available_models(provider)
        }
    
    @classmethod
    def _get_available_models(cls, provider):
        """Get available models for a provider."""
        models = {
            'openai': [
                'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo',
            ],
            'azure': [
                'gpt-4o', 'gpt-4', 'gpt-35-turbo',
            ],
            'anthropic': [
                'claude-opus-4-20250514', 'claude-sonnet-4-20250514',
                'claude-haiku-4-5-20251001',
            ],
            'ollama': [
                'llama3.1', 'llama3.1:70b', 'mistral', 'codellama',
            ],
        }
        return models.get(provider, [])







































