"""pgvector factory — builds LangChain PGVector store + retriever.

Uses ``langchain_postgres.PGVector`` which manages its own collection
table inside the application's PostgreSQL database.  No external
vector service required.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _normalize_sqlalchemy_url(url: str) -> str:
    """Normalize a DB URL for SQLAlchemy + psycopg3.

    SQLAlchemy dropped the ``postgres://`` scheme long ago — it only recognises
    ``postgresql://`` (and driver-specific variants like ``postgresql+psycopg://``).
    Django / psycopg still accept ``postgres://``, so production ``DATABASE_URL``
    values routinely ship with the legacy scheme and blow up PGVector.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _get_connection_string() -> str:
    """Derive a psycopg-compatible connection string from Django settings."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return _normalize_sqlalchemy_url(db_url)

    # Fall back to individual DB_* env vars (mirrors prod settings)
    host = os.environ.get("DB_HOST", "db")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", os.environ.get("POSTGRES_DB", "wanjala-api-database"))
    user = os.environ.get("DB_USER", os.environ.get("POSTGRES_USER", "wanjala-art-sql-user"))
    password = os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def build_pgvector_store(
    collection_name: str | None = None,
    embeddings_instance=None,
    **kwargs,
):
    """Build a LangChain PGVector store backed by the application database.

    The store auto-creates the ``langchain_pg_collection`` and
    ``langchain_pg_embedding`` tables on first use.
    """
    from langchain_postgres import PGVector
    from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory

    if not collection_name:
        collection_name = os.environ.get("PGVECTOR_COLLECTION", "ai_documents")

    if not embeddings_instance:
        embeddings_instance = EmbeddingsFactory.create_embeddings(provider="openai")

    connection = _get_connection_string()

    return PGVector(
        collection_name=collection_name,
        embeddings=embeddings_instance,
        connection=connection,
        use_jsonb=True,
    )


def build_pgvector_retriever(
    chat_args=None,
    k: int = 4,
    vector_store=None,
    embeddings_instance=None,
    **kwargs,
):
    """Build a LangChain retriever from a PGVector store."""
    if not vector_store:
        vector_store = build_pgvector_store(embeddings_instance=embeddings_instance)

    # Build metadata filter from chat_args
    pg_filter: dict | None = None
    if chat_args:
        conditions = {}
        pdf_id = getattr(chat_args, "pdf_id", None)
        workspace_id = getattr(chat_args, "workspace_id", None)
        user_id = getattr(chat_args, "user_id", None)

        if pdf_id:
            conditions["pdf_id"] = str(pdf_id)
        if workspace_id:
            conditions["workspace_id"] = str(workspace_id)
        if user_id:
            conditions["user_id"] = str(user_id)

        if conditions:
            pg_filter = conditions

    search_kwargs: dict = {"k": k}
    if pg_filter:
        search_kwargs["filter"] = pg_filter

    return vector_store.as_retriever(search_kwargs=search_kwargs)
