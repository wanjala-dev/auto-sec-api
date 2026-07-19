"""Provider for content ORM model classes.

Controllers under ``components/content/api/*`` consume
:class:`ContentModelsProvider` instead of importing the concrete Django
models directly. Keeps the API layer's import graph free of
infrastructure dependencies — enforced by the architecture test
``test_controllers_do_not_import_concrete_adapters``.

All ``infrastructure.persistence.content`` imports happen lazily inside
property bodies so that loading this module has no Django-app side
effects (it can be imported at process boot, before settings.configure).
"""

from __future__ import annotations

from typing import Any


class ContentModelsProvider:
    """Driving-side façade for content ORM model classes.

    Each property lazy-imports the concrete Django model class from
    ``infrastructure.persistence.content.models`` and returns it. Call
    sites continue to use the class exactly as before (``Model.objects
    .filter(...)``); only the *acquisition* of the class is indirected.
    """

    @property
    def Subscriber(self) -> Any:
        from infrastructure.persistence.content.models import Subscriber

        return Subscriber

    @property
    def SuppressedAddress(self) -> Any:
        from infrastructure.persistence.content.models import SuppressedAddress

        return SuppressedAddress

    @property
    def Newsletter(self) -> Any:
        from infrastructure.persistence.content.models import Newsletter

        return Newsletter

    @property
    def WritingTemplate(self) -> Any:
        from infrastructure.persistence.content.models import WritingTemplate

        return WritingTemplate

    @property
    def WritingDraft(self) -> Any:
        from infrastructure.persistence.content.models import WritingDraft

        return WritingDraft


_default = ContentModelsProvider()


def get_content_models_provider() -> ContentModelsProvider:
    """Return the default provider — composition root for content ORM
    model class lookup. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
