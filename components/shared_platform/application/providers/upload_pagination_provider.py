"""Provider/composition root for the default DRF pagination class.

Controllers MUST consume :class:`UploadPaginationProvider` instead of
importing
``components.shared_platform.infrastructure.services.upload_pagination``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.
"""

from __future__ import annotations

from typing import Any


class UploadPaginationProvider:
    """Driving-side façade for the default uploads pagination class."""

    def get_pagination_class(self) -> Any:
        from components.shared_platform.infrastructure.services.upload_pagination import (
            DefaultPagination,
        )

        return DefaultPagination


_default = UploadPaginationProvider()


def get_upload_pagination_provider() -> UploadPaginationProvider:
    """Return the default provider — composition root for the uploads
    pagination class.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
