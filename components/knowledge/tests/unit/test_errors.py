"""Unit tests for knowledge domain errors."""

from __future__ import annotations

import pytest

from components.knowledge.domain.errors import DomainError, UnsupportedProviderError
from components.shared_kernel.domain.errors import ValidationError


class TestDomainError:
    """Tests for DomainError base class."""

    def test_domain_error_can_be_raised(self) -> None:
        """Test that DomainError can be raised and caught."""
        with pytest.raises(DomainError) as exc_info:
            raise DomainError("Test error")

        assert str(exc_info.value) == "Test error"

    def test_domain_error_with_empty_message(self) -> None:
        """Test that DomainError works with empty message."""
        error = DomainError("")
        assert str(error) == ""

    def test_domain_error_with_multiline_message(self) -> None:
        """Test that DomainError preserves multiline messages."""
        msg = "Line 1\nLine 2\nLine 3"
        error = DomainError(msg)
        assert str(error) == msg


class TestUnsupportedProviderError:
    """Tests for UnsupportedProviderError."""

    def test_is_domain_error(self) -> None:
        """Test that UnsupportedProviderError is a DomainError."""
        error = UnsupportedProviderError("embeddings", "unknown", ["openai", "azure"])
        assert isinstance(error, DomainError)

    def test_is_validation_error(self) -> None:
        """Test that UnsupportedProviderError is a ValidationError."""
        error = UnsupportedProviderError("embeddings", "unknown", ["openai", "azure"])
        assert isinstance(error, ValidationError)

    def test_error_message_format(self) -> None:
        """Test the error message format."""
        error = UnsupportedProviderError("embeddings", "openai", ["azure", "elasticsearch"])

        expected_msg = (
            "Unsupported embeddings provider: 'openai'. "
            "Available: azure, elasticsearch"
        )
        assert str(error) == expected_msg

    def test_error_attributes_stored(self) -> None:
        """Test that error attributes are accessible."""
        error = UnsupportedProviderError("llm", "custom", ["anthropic", "openai"])

        assert error.kind == "llm"
        assert error.provider == "custom"
        assert error.available == ["anthropic", "openai"]

    def test_error_message_with_single_available(self) -> None:
        """Test error message with single available provider."""
        error = UnsupportedProviderError("vector_store", "milvus", ["pinecone"])

        expected_msg = (
            "Unsupported vector_store provider: 'milvus'. "
            "Available: pinecone"
        )
        assert str(error) == expected_msg

    def test_error_message_with_many_available(self) -> None:
        """Test error message with many available providers."""
        available = ["pinecone", "weaviate", "milvus", "opensearch", "elasticsearch"]
        error = UnsupportedProviderError("vector_store", "unknown", available)

        # Check that all providers are listed in sorted order
        error_msg = str(error)
        assert "elasticsearch" in error_msg
        assert "milvus" in error_msg
        assert "opensearch" in error_msg
        assert "pinecone" in error_msg
        assert "weaviate" in error_msg

    def test_error_message_with_empty_available_list(self) -> None:
        """Test error message when no providers are available."""
        error = UnsupportedProviderError("embeddings", "openai", [])

        expected_msg = (
            "Unsupported embeddings provider: 'openai'. "
            "Available: "
        )
        assert str(error) == expected_msg

    def test_available_list_is_sorted(self) -> None:
        """Test that available providers are sorted in error message."""
        unsorted = ["zebra", "alpha", "charlie", "beta"]
        error = UnsupportedProviderError("test", "unknown", unsorted)

        error_msg = str(error)
        # Extract the available part from the message
        available_part = error_msg.split("Available: ")[1]
        providers_in_msg = available_part.split(", ")

        # Check that they are sorted
        assert providers_in_msg == sorted(providers_in_msg)

    def test_error_can_be_raised_and_caught_as_domain_error(self) -> None:
        """Test that error can be caught as DomainError."""
        with pytest.raises(DomainError):
            raise UnsupportedProviderError("embeddings", "gpt4", ["openai"])

    def test_error_can_be_raised_and_caught_as_validation_error(self) -> None:
        """Test that error can be caught as ValidationError."""
        with pytest.raises(ValidationError):
            raise UnsupportedProviderError("embeddings", "gpt4", ["openai"])

    def test_error_can_be_raised_and_caught_as_unsupported_provider_error(self) -> None:
        """Test that error can be caught as UnsupportedProviderError."""
        with pytest.raises(UnsupportedProviderError):
            raise UnsupportedProviderError("embeddings", "gpt4", ["openai"])

    def test_error_with_special_characters_in_provider(self) -> None:
        """Test error message with special characters in provider name."""
        error = UnsupportedProviderError(
            "embeddings",
            "custom-provider_v2",
            ["openai", "azure"]
        )

        assert "custom-provider_v2" in str(error)

    def test_error_with_various_kind_values(self) -> None:
        """Test error with various kind values."""
        kinds = ["embeddings", "llm", "vector_store", "retriever", "custom_component"]

        for kind in kinds:
            error = UnsupportedProviderError(kind, "unknown", ["provider1"])
            assert f"Unsupported {kind} provider" in str(error)
            assert error.kind == kind

    def test_error_with_duplicate_available_providers(self) -> None:
        """Test error with duplicate providers in available list."""
        error = UnsupportedProviderError(
            "embeddings",
            "unknown",
            ["openai", "azure", "openai", "anthropic", "azure"]
        )

        error_msg = str(error)
        # The message should still be created successfully
        assert "Unknown" not in error_msg  # provider name is 'unknown'
        assert "embeddings" in error_msg
        # Duplicates should remain as provided (sorted but with duplicates)
        assert error.available == ["openai", "azure", "openai", "anthropic", "azure"]

    def test_error_with_empty_kind_string(self) -> None:
        """Test error with empty kind string."""
        error = UnsupportedProviderError("", "unknown", ["provider1"])

        expected_msg = (
            "Unsupported  provider: 'unknown'. "
            "Available: provider1"
        )
        assert str(error) == expected_msg
        assert error.kind == ""

    def test_error_with_whitespace_provider(self) -> None:
        """Test error with whitespace in provider name."""
        error = UnsupportedProviderError(
            "embeddings",
            "my custom provider",
            ["openai"]
        )

        assert "my custom provider" in str(error)

    def test_error_chaining(self) -> None:
        """Test that error can be chained with __cause__."""
        try:
            try:
                raise KeyError("Missing config key")
            except KeyError as e:
                raise UnsupportedProviderError("embeddings", "unknown", []) from e
        except UnsupportedProviderError as e:
            assert isinstance(e.__cause__, KeyError)
            assert str(e.__cause__) == "'Missing config key'"

    def test_error_context(self) -> None:
        """Test that error can have context."""
        try:
            try:
                raise ValueError("Invalid provider config")
            except ValueError:
                raise UnsupportedProviderError("llm", "custom", ["openai"])
        except UnsupportedProviderError as e:
            assert isinstance(e.__context__, ValueError)

    def test_attributes_not_modified_after_creation(self) -> None:
        """Test that error attributes are preserved after creation."""
        kind = "embeddings"
        provider = "openai"
        available = ["azure", "anthropic"]

        error = UnsupportedProviderError(kind, provider, available)

        # Attributes should match exactly what was passed
        assert error.kind == kind
        assert error.provider == provider
        assert error.available == available
