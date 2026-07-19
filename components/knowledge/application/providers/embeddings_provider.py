"""Provider/composition root for knowledge embedding creators.

External controllers (e.g. ``components/agents/api/controller.py``)
should consume :class:`EmbeddingsProvider` instead of importing the
concrete adapters in ``components/knowledge/infrastructure/adapters/``.
The test ``test_controllers_do_not_import_concrete_adapters``
enforces this.
"""

from __future__ import annotations

from typing import Any


class EmbeddingsProvider:
    """Façade exposing the knowledge embedding factories.

    Methods lazy-import the adapter so module load is cheap and the
    import graph never crosses the controller-→ infrastructure
    boundary.
    """

    def create_for_pdf(self, *args, **kwargs) -> Any:
        from components.knowledge.infrastructure.adapters.pdf_embeddings import (
            create_embeddings_for_pdf,
        )

        return create_embeddings_for_pdf(*args, **kwargs)

    def create_for_document(self, *args, **kwargs) -> Any:
        from components.knowledge.infrastructure.adapters.document_embeddings import (
            create_embeddings_for_document,
        )

        return create_embeddings_for_document(*args, **kwargs)


_default = EmbeddingsProvider()


def get_embeddings_provider() -> EmbeddingsProvider:
    """Return the default provider — composition root for knowledge
    embedding creators. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
