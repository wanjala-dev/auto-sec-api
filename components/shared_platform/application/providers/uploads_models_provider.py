"""Provider for ORM model classes in ``infrastructure.persistence.uploads``.

Controllers (and any other application-layer code) should obtain ORM model
classes through this provider instead of importing them directly from
``infrastructure.persistence.uploads.*``.

This preserves Explicit Architecture's layering rule that application /
interface code does not statically depend on infrastructure: every model
import happens lazily inside the property body, so this module's top-level
imports stay framework-free (stdlib + ``typing`` only).

Usage::

    from components.shared_platform.application.providers.uploads_models_provider import (
        get_uploads_models_provider,
    )

    File = get_uploads_models_provider().File
    File.objects.filter(...)
"""

from __future__ import annotations

from typing import Any


class UploadsModelsProvider:
    """Façade exposing ORM model classes from ``infrastructure.persistence.uploads``.

    Each property lazy-imports the underlying Django model class so this
    module remains framework-free at import time.
    """

    @property
    def File(self) -> Any:
        from infrastructure.persistence.uploads.models import File
        return File


_default = UploadsModelsProvider()


def get_uploads_models_provider() -> UploadsModelsProvider:
    """Return the default :class:`UploadsModelsProvider` instance."""
    return _default
