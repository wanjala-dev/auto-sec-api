"""Unit tests for DocumentEntity and DocumentChunkEntity."""

from __future__ import annotations

import datetime
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from components.knowledge.domain.entities.document_entity import (
    DocumentChunkEntity,
    DocumentEntity,
)


class TestDocumentEntity:
    """Tests for DocumentEntity."""

    def test_construct_with_required_fields(self) -> None:
        """Test constructing a document with only required fields."""
        doc_id = uuid4()

        doc = DocumentEntity(
            id=doc_id,
            title="Test Document",
            content="This is test content",
        )

        assert doc.id == doc_id
        assert doc.title == "Test Document"
        assert doc.content == "This is test content"
        assert doc.source == ""
        assert doc.metadata == {}
        assert doc.created_at is None
        assert doc.updated_at is None

    def test_construct_with_all_fields(self) -> None:
        """Test constructing a document with all fields."""
        doc_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
        metadata = {"tags": ["important", "review"], "category": "technical"}

        doc = DocumentEntity(
            id=doc_id,
            title="Complete Document",
            content="Full content here",
            source="https://example.com/doc",
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
        )

        assert doc.id == doc_id
        assert doc.title == "Complete Document"
        assert doc.content == "Full content here"
        assert doc.source == "https://example.com/doc"
        assert doc.metadata == metadata
        assert doc.created_at == created_at
        assert doc.updated_at == updated_at

    def test_construct_with_empty_title(self) -> None:
        """Test constructing a document with empty title (no validation)."""
        doc_id = uuid4()

        doc = DocumentEntity(
            id=doc_id,
            title="",
            content="Content",
        )

        assert doc.title == ""

    def test_construct_with_empty_content(self) -> None:
        """Test constructing a document with empty content (no validation)."""
        doc_id = uuid4()

        doc = DocumentEntity(
            id=doc_id,
            title="Title",
            content="",
        )

        assert doc.content == ""

    def test_construct_with_empty_metadata_dict(self) -> None:
        """Test constructing a document with explicitly empty metadata."""
        doc_id = uuid4()

        doc = DocumentEntity(
            id=doc_id,
            title="Title",
            content="Content",
            metadata={},
        )

        assert doc.metadata == {}

    def test_metadata_default_factory(self) -> None:
        """Test that metadata defaults to empty dict via factory."""
        doc_id = uuid4()

        doc1 = DocumentEntity(id=doc_id, title="Doc1", content="Content1")
        doc2 = DocumentEntity(
            id=uuid4(), title="Doc2", content="Content2"
        )

        # Each should have its own metadata dict
        assert doc1.metadata is not doc2.metadata
        assert doc1.metadata == {}
        assert doc2.metadata == {}

    def test_entity_is_frozen(self) -> None:
        """Test that DocumentEntity is immutable."""
        doc_id = uuid4()

        doc = DocumentEntity(
            id=doc_id,
            title="Immutable",
            content="Content",
        )

        with pytest.raises(FrozenInstanceError):
            doc.title = "Modified"

    def test_entity_equality(self) -> None:
        """Test that two entities with same data are equal."""
        doc_id = uuid4()

        doc1 = DocumentEntity(
            id=doc_id,
            title="Same",
            content="Same content",
        )

        doc2 = DocumentEntity(
            id=doc_id,
            title="Same",
            content="Same content",
        )

        assert doc1 == doc2

    def test_entity_inequality_different_id(self) -> None:
        """Test that entities with different IDs are not equal."""
        doc1 = DocumentEntity(
            id=uuid4(),
            title="Same",
            content="Same content",
        )

        doc2 = DocumentEntity(
            id=uuid4(),
            title="Same",
            content="Same content",
        )

        assert doc1 != doc2

    def test_entity_inequality_different_title(self) -> None:
        """Test that entities with different titles are not equal."""
        doc_id = uuid4()

        doc1 = DocumentEntity(
            id=doc_id,
            title="Title1",
            content="Same content",
        )

        doc2 = DocumentEntity(
            id=doc_id,
            title="Title2",
            content="Same content",
        )

        assert doc1 != doc2

    def test_entity_inequality_different_content(self) -> None:
        """Test that entities with different content are not equal."""
        doc_id = uuid4()

        doc1 = DocumentEntity(
            id=doc_id,
            title="Same",
            content="Content1",
        )

        doc2 = DocumentEntity(
            id=doc_id,
            title="Same",
            content="Content2",
        )

        assert doc1 != doc2

    def test_source_default_empty_string(self) -> None:
        """Test that source defaults to empty string."""
        doc = DocumentEntity(
            id=uuid4(),
            title="Title",
            content="Content",
        )

        assert doc.source == ""
        assert isinstance(doc.source, str)

    def test_with_various_metadata_structures(self) -> None:
        """Test documents with various metadata structures."""
        doc_id = uuid4()

        # Nested metadata
        metadata = {
            "author": "John Doe",
            "nested": {"level2": {"level3": "value"}},
            "tags": ["tag1", "tag2", "tag3"],
            "stats": {"words": 1000, "pages": 5},
        }

        doc = DocumentEntity(
            id=doc_id,
            title="Complex Metadata",
            content="Content",
            metadata=metadata,
        )

        assert doc.metadata == metadata
        assert doc.metadata["author"] == "John Doe"
        assert doc.metadata["nested"]["level2"]["level3"] == "value"

    def test_with_datetime_values(self) -> None:
        """Test documents with datetime fields."""
        doc_id = uuid4()
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        past = now - datetime.timedelta(days=1)

        doc = DocumentEntity(
            id=doc_id,
            title="Timestamped",
            content="Content",
            created_at=past,
            updated_at=now,
        )

        assert doc.created_at == past
        assert doc.updated_at == now
        assert doc.updated_at > doc.created_at

    def test_with_long_title(self) -> None:
        """Test document with very long title."""
        doc_id = uuid4()
        long_title = "A" * 10000

        doc = DocumentEntity(
            id=doc_id,
            title=long_title,
            content="Content",
        )

        assert len(doc.title) == 10000
        assert doc.title == long_title

    def test_with_long_content(self) -> None:
        """Test document with very long content."""
        doc_id = uuid4()
        long_content = "Lorem ipsum " * 100000

        doc = DocumentEntity(
            id=doc_id,
            title="Long",
            content=long_content,
        )

        assert len(doc.content) == len(long_content)


class TestDocumentChunkEntity:
    """Tests for DocumentChunkEntity."""

    def test_construct_with_required_fields(self) -> None:
        """Test constructing a document chunk with required fields."""
        chunk_id = uuid4()
        doc_id = uuid4()

        chunk = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Chunk content",
            chunk_index=0,
        )

        assert chunk.id == chunk_id
        assert chunk.document_id == doc_id
        assert chunk.content == "Chunk content"
        assert chunk.chunk_index == 0
        assert chunk.metadata == {}
        assert chunk.created_at is None

    def test_construct_with_all_fields(self) -> None:
        """Test constructing a document chunk with all fields."""
        chunk_id = uuid4()
        doc_id = uuid4()
        created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        metadata = {"position": "middle", "hash": "abc123"}

        chunk = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Full chunk content",
            chunk_index=5,
            metadata=metadata,
            created_at=created_at,
        )

        assert chunk.id == chunk_id
        assert chunk.document_id == doc_id
        assert chunk.content == "Full chunk content"
        assert chunk.chunk_index == 5
        assert chunk.metadata == metadata
        assert chunk.created_at == created_at

    def test_chunk_index_zero(self) -> None:
        """Test chunk with index 0 (first chunk)."""
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="First chunk",
            chunk_index=0,
        )

        assert chunk.chunk_index == 0

    def test_chunk_index_large_number(self) -> None:
        """Test chunk with large index."""
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Last chunk",
            chunk_index=999999,
        )

        assert chunk.chunk_index == 999999

    def test_chunk_index_negative(self) -> None:
        """Test chunk with negative index (no validation)."""
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Negative index",
            chunk_index=-1,
        )

        assert chunk.chunk_index == -1

    def test_metadata_default_factory(self) -> None:
        """Test that metadata defaults to empty dict via factory."""
        chunk1 = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Chunk1",
            chunk_index=0,
        )

        chunk2 = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Chunk2",
            chunk_index=1,
        )

        # Each should have its own metadata dict
        assert chunk1.metadata is not chunk2.metadata
        assert chunk1.metadata == {}
        assert chunk2.metadata == {}

    def test_entity_is_frozen(self) -> None:
        """Test that DocumentChunkEntity is immutable."""
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Immutable",
            chunk_index=0,
        )

        with pytest.raises(FrozenInstanceError):
            chunk.content = "Modified"

    def test_entity_equality(self) -> None:
        """Test that two entities with same data are equal."""
        chunk_id = uuid4()
        doc_id = uuid4()

        chunk1 = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Same content",
            chunk_index=3,
        )

        chunk2 = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Same content",
            chunk_index=3,
        )

        assert chunk1 == chunk2

    def test_entity_inequality_different_id(self) -> None:
        """Test that entities with different IDs are not equal."""
        doc_id = uuid4()

        chunk1 = DocumentChunkEntity(
            id=uuid4(),
            document_id=doc_id,
            content="Same",
            chunk_index=0,
        )

        chunk2 = DocumentChunkEntity(
            id=uuid4(),
            document_id=doc_id,
            content="Same",
            chunk_index=0,
        )

        assert chunk1 != chunk2

    def test_entity_inequality_different_document_id(self) -> None:
        """Test that entities with different document IDs are not equal."""
        chunk_id = uuid4()

        chunk1 = DocumentChunkEntity(
            id=chunk_id,
            document_id=uuid4(),
            content="Same",
            chunk_index=0,
        )

        chunk2 = DocumentChunkEntity(
            id=chunk_id,
            document_id=uuid4(),
            content="Same",
            chunk_index=0,
        )

        assert chunk1 != chunk2

    def test_entity_inequality_different_chunk_index(self) -> None:
        """Test that entities with different indices are not equal."""
        chunk_id = uuid4()
        doc_id = uuid4()

        chunk1 = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Same",
            chunk_index=0,
        )

        chunk2 = DocumentChunkEntity(
            id=chunk_id,
            document_id=doc_id,
            content="Same",
            chunk_index=1,
        )

        assert chunk1 != chunk2

    def test_chunk_with_empty_content(self) -> None:
        """Test chunk with empty content (no validation)."""
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="",
            chunk_index=0,
        )

        assert chunk.content == ""

    def test_chunk_with_multiline_content(self) -> None:
        """Test chunk with multiline content."""
        content = "Line 1\nLine 2\nLine 3\n\nLine 5"
        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content=content,
            chunk_index=2,
        )

        assert chunk.content == content
        assert "\n" in chunk.content

    def test_sequential_chunks(self) -> None:
        """Test creating a sequence of chunks."""
        doc_id = uuid4()
        chunks = []

        for i in range(5):
            chunk = DocumentChunkEntity(
                id=uuid4(),
                document_id=doc_id,
                content=f"Chunk {i}",
                chunk_index=i,
            )
            chunks.append(chunk)

        assert len(chunks) == 5
        assert all(chunk.document_id == doc_id for chunk in chunks)
        assert [c.chunk_index for c in chunks] == [0, 1, 2, 3, 4]

    def test_chunk_with_complex_metadata(self) -> None:
        """Test chunk with complex metadata."""
        metadata = {
            "line_number": 42,
            "word_count": 150,
            "embedding_model": "openai/text-embedding-3-small",
            "processing_stats": {
                "tokenized": True,
                "tokens": 45,
                "language": "en",
            },
            "references": ["ref1", "ref2", "ref3"],
        }

        chunk = DocumentChunkEntity(
            id=uuid4(),
            document_id=uuid4(),
            content="Metadata chunk",
            chunk_index=0,
            metadata=metadata,
        )

        assert chunk.metadata == metadata
        assert chunk.metadata["word_count"] == 150
        assert chunk.metadata["processing_stats"]["tokenized"] is True
