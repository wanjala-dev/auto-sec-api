"""Tests for embeddings factory provider discovery."""

import pytest

from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory


def test_factory_exposes_core_providers():
    providers = EmbeddingsFactory.get_available_providers()
    assert "openai" in providers
    assert "azure" in providers


def test_create_embeddings_rejects_unknown_provider():
    with pytest.raises(ValueError):
        EmbeddingsFactory.create_embeddings(provider="nonexistent")
