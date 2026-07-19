"""Application-layer facade exposing content documents to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
try:
    from components.content.infrastructure.adapters.news_documents import (
        CategoryDocument,
        NewsDocument,
        UserDocument,
    )
except (ImportError, ModuleNotFoundError):
    CategoryDocument = None
    NewsDocument = None
    UserDocument = None

__all__ = ["CategoryDocument", "NewsDocument", "UserDocument"]
