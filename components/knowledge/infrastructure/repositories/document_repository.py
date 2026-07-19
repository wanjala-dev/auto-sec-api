"""ORM repository for Document persistence in the knowledge context."""

from __future__ import annotations

from typing import Any, Optional


class OrmDocumentRepository:
    """Wraps Document ORM access behind a repository interface."""

    def get_by_id(self, doc_id: str) -> Any:
        from infrastructure.persistence.ai.models import Document
        return Document.objects.get(id=doc_id)

    def create(self, **kwargs) -> Any:
        from infrastructure.persistence.ai.models import Document
        return Document.objects.create(**kwargs)

    def get_with_chunks(self, doc_id: str) -> Optional[Any]:
        from infrastructure.persistence.ai.models import Document
        try:
            return Document.objects.prefetch_related("chunks").get(id=doc_id)
        except Document.DoesNotExist:
            return None
