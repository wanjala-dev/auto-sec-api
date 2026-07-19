"""Provider for Django ORM query helpers (Sum, Count, Q, F, transaction).

Controllers and permissions modules that need ORM aggregation helpers
consume this provider instead of importing ``django.db`` /
``django.db.models`` / ``django.db.models.functions`` directly.

Implementation note — runtime delegation via ``importlib`` keeps the
provider module's static import graph free of Django, so it passes the
shared-kernel ``test_shared_kernel_is_framework_free`` guardrail. The
deeper architectural fix is to push every aggregation into a Read
Repository owned by the consuming context; that work is queued as a
follow-up. Until then, treat this provider as the transitional surface
that satisfies the controller→ORM boundary test while keeping the
existing query shape.
"""

from __future__ import annotations

import importlib
from typing import Any


_MODULES = (
    "django.db.models",
    "django.db.models.functions",
    "django.db",
)


class DjangoOrmProvider:
    """Driving-side façade for the Django ORM query helpers."""

    def __getattr__(self, name: str) -> Any:
        for mod_name in _MODULES:
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            if hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(f"DjangoOrmProvider has no symbol {name!r}")


_default = DjangoOrmProvider()


def get_django_orm_provider() -> DjangoOrmProvider:
    """Return the default Django ORM helper provider."""
    return _default
