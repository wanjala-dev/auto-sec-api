import pytest

from components.knowledge.infrastructure.factories.embeddings import factory


@pytest.fixture(autouse=True)
def stub_providers(monkeypatch):
    outputs = {}

    def make_builder(name):
        def _builder(**kwargs):
            outputs["last"] = (name, kwargs)
            return {"name": name, "kwargs": kwargs}

        return _builder

    monkeypatch.setattr(factory, "build_openai_embeddings", make_builder("openai"))
    monkeypatch.setattr(factory, "build_azure_embeddings", make_builder("azure"))
    monkeypatch.setattr(factory, "build_elasticsearch_native_embeddings", make_builder("elasticsearch_native"))
    monkeypatch.setattr(factory, "ELASTICSEARCH_NATIVE_IMPORTED", False)
    monkeypatch.delenv("ENABLE_ES_NATIVE_EMBEDDINGS", raising=False)

    return outputs


def test_get_providers_defaults(stub_providers):
    providers = factory.EmbeddingsFactory._get_providers()

    assert set(providers.keys()) == {"openai", "azure"}
    result = providers["openai"](temperature=0.1)
    assert result["name"] == "openai"
    assert result["kwargs"]["temperature"] == 0.1
    assert stub_providers["last"][0] == "openai"


def test_get_providers_includes_elasticsearch_when_env_enabled(monkeypatch):
    monkeypatch.setattr(factory, "ELASTICSEARCH_NATIVE_IMPORTED", True)
    monkeypatch.setenv("ENABLE_ES_NATIVE_EMBEDDINGS", "true")

    providers = factory.EmbeddingsFactory._get_providers()

    assert "elasticsearch_native" in providers
    result = providers["elasticsearch_native"](index="documents")
    assert result["kwargs"]["index"] == "documents"


def test_create_embeddings_uses_requested_provider(stub_providers):
    embedding = factory.EmbeddingsFactory.create_embeddings(
        provider="azure",
        deployment="text-embedding",
    )

    assert embedding["name"] == "azure"
    assert embedding["kwargs"]["deployment"] == "text-embedding"
    assert stub_providers["last"][0] == "azure"


def test_create_embeddings_unknown_provider_raises():
    with pytest.raises(ValueError):
        factory.EmbeddingsFactory.create_embeddings(provider="unsupported")


def test_get_provider_info_returns_available_models(monkeypatch):
    monkeypatch.setattr(factory.EmbeddingsFactory, "_get_providers", classmethod(lambda cls: {"openai": object}))

    info = factory.EmbeddingsFactory.get_provider_info("openai")

    assert info["provider"] == "openai"
    assert "text-embedding-ada-002" in info["available_models"]


def test_get_provider_info_missing_provider_returns_none(monkeypatch):
    monkeypatch.setattr(factory.EmbeddingsFactory, "_get_providers", classmethod(lambda cls: {"openai": object}))

    assert factory.EmbeddingsFactory.get_provider_info("azure") is None
