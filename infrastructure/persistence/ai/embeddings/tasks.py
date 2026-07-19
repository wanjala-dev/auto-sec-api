"""Celery task shim — delegates to canonical component module.

This file exists so that ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) can find and register the tasks defined in the
components layer.
"""
from components.knowledge.infrastructure.tasks.embedding_tasks import (  # noqa: F401
    create_embeddings_for_all_content,
    create_embeddings_for_conversations,
    create_embeddings_for_workspace,
    create_embeddings_for_workspace_content,
)
