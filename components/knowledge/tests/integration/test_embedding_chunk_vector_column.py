"""The pgvector RAG store must actually HAVE the column it searches.

``ai_embedding_chunks`` is the workspace-RAG store: the workspace snapshot
indexer, the uploaded-document indexer and Remediation Memory all write rows
into it, and every retrieval path in
:mod:`components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter`
reads them back with SQL that names ``embedding``::

    SELECT content, metadata, 1 - (embedding <=> %s::vector) AS score
    FROM ai_embedding_chunks
    WHERE embedding IS NOT NULL

For months no migration created that column. The fork's migration reset
(fresh ``0001``s, see CLAUDE.md "How to self-correct when the fork bites")
dropped the RunSQL step the model docstring still advertised, and nothing
noticed because:

* the column was never declared on the ORM model, so ``makemigrations``
  had nothing to compare against and reported no drift;
* pytest skips migrations (``django_db_use_migrations=False``), so the test
  database is built from the models — which also lacked the column;
* the writers probe for the pgvector EXTENSION, not for the column, and the
  extension IS present on the live database (``langchain-postgres`` creates
  it), so ``UPDATE ai_embedding_chunks SET embedding = ...`` ran and raised
  ``UndefinedColumn`` into a broad ``except`` on the write side.

Net effect on the live cluster: every vector search raised ``UndefinedColumn``
and workspace RAG grounding returned nothing. These tests pin the column from
both directions — the migration graph (what a deployed database gets) and the
live table (what the ORM contract promises).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

EXPECTED_DIMENSIONS = 1536  # text-embedding-ada-002 / text-embedding-3-small


def _embedding_chunk_migration_state():
    """Project state for ``ai.EmbeddingChunk`` as MIGRATIONS build it.

    pytest-django implements ``django_db_use_migrations=False`` by swapping
    ``settings.MIGRATION_MODULES`` for a mapping that answers ``None`` for
    every app, which makes every app look unmigrated to the loader. Restoring
    the real (empty) mapping for the duration of this read is what lets the
    suite assert on the migration graph while still building its own test
    database from the models.
    """
    with override_settings(MIGRATION_MODULES={}):
        state = MigrationLoader(None, ignore_no_migrations=True).project_state()
    return state.models["ai", "embeddingchunk"]


class TestMigrationGraphCreatesTheEmbeddingColumn:
    """A deployed database is built by MIGRATIONS, not by the models.

    pytest skips migrations, so a model-only assertion would stay green
    while every real Postgres kept a table with no ``embedding`` column —
    which is exactly the blind spot that let this ship. Assert against the
    migration graph itself.
    """

    def test_ai_migrations_declare_the_embedding_field(self):
        field_names = list(_embedding_chunk_migration_state().fields)

        assert "embedding" in field_names, (
            "No migration in the `ai` app creates `ai_embedding_chunks.embedding`. "
            "Every pgvector search (`1 - (embedding <=> %s::vector)`) raises "
            f"UndefinedColumn on a freshly migrated database. Fields present: {field_names}"
        )

    def test_embedding_field_is_a_vector_of_the_embedding_dimension(self):
        """The column type must be the pgvector ``vector`` type at the
        embedding model's dimension — a plain text/JSON column would accept
        writes and then fail the ``<=>`` distance operator at read time."""
        field = _embedding_chunk_migration_state().fields["embedding"]

        assert type(field).__name__ == "VectorField", (
            f"`embedding` is a {type(field).__name__}; the pgvector distance "
            "operators require the `vector` column type."
        )
        assert field.dimensions == EXPECTED_DIMENSIONS
        assert field.null is True, (
            "Rows are inserted first and the vector attached afterwards, so the column must be nullable."
        )


@pytest.mark.django_db
class TestLiveTableCarriesTheEmbeddingColumn:
    def test_ai_embedding_chunks_has_an_embedding_column(self):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, EmbeddingChunk._meta.db_table)
        columns = [column.name for column in description]

        assert "embedding" in columns, (
            f"`{EmbeddingChunk._meta.db_table}` has columns {columns} — no "
            "`embedding`. The vector store writes it by raw SQL and reads it "
            "in every search; without the column both sides raise."
        )
