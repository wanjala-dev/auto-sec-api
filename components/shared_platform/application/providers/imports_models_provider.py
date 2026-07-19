"""Provider for ORM model classes living in ``infrastructure.persistence.imports``.

Controllers (under ``components/*/api/``) MUST consume
:class:`ImportsModelsProvider` instead of importing the ORM model classes
directly from ``infrastructure.persistence.imports.models``. Keeps the API
layer's import graph free of concrete persistence dependencies
— enforced by the architecture test
``test_controllers_do_not_import_concrete_adapters``.

Each model is exposed as a lazy ``@property`` that imports the class inside
the method body, so importing this module never pulls Django ORM state at
module top.
"""

from __future__ import annotations

from typing import Any


class ImportsModelsProvider:
    """Driving-side façade for ``infrastructure.persistence.imports`` models.

    Use the properties — never reach into the persistence package directly
    from controllers.
    """

    @property
    def DocumentImport(self) -> Any:
        from infrastructure.persistence.imports.models import DocumentImport

        return DocumentImport

    @property
    def DocumentImportRow(self) -> Any:
        from infrastructure.persistence.imports.models import DocumentImportRow

        return DocumentImportRow


_default = ImportsModelsProvider()


def get_imports_models_provider() -> ImportsModelsProvider:
    """Return the default provider — composition root for the
    ``infrastructure.persistence.imports`` model classes.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
