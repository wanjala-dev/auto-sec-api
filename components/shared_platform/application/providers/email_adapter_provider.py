"""Provider for the shared-platform Django email adapter.

Cross-context callers (receipts) consume this provider instead of
importing
``components.shared_platform.infrastructure.adapters.django_email_adapter``
directly.
"""

from __future__ import annotations

from typing import Any


class EmailAdapterProvider:
    def adapter(self) -> Any:
        from components.shared_platform.infrastructure.adapters.django_email_adapter import (
            DjangoEmailAdapter,
        )

        return DjangoEmailAdapter()


_default = EmailAdapterProvider()


def get_email_adapter_provider() -> EmailAdapterProvider:
    return _default
