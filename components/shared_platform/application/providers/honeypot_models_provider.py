"""Composition-root provider for honeypot ORM models.

Controllers MUST consume :class:`HoneypotModelsProvider` instead of
importing ``infrastructure.persistence.honeypot.models`` directly. The arch
test ``test_controllers_do_not_import_orm_models`` enforces this.

The provider is framework-free at module top — only stdlib + typing imports.
Each model class is lazy-imported inside the corresponding property so the
import graph stays free of infrastructure imports at module load time.
"""

from __future__ import annotations

from typing import Any


class HoneypotModelsProvider:
    """Driving-side façade exposing honeypot ORM model classes."""

    @property
    def HoneypotAttempt(self) -> Any:
        from infrastructure.persistence.honeypot.models import HoneypotAttempt

        return HoneypotAttempt


_default = HoneypotModelsProvider()


def get_honeypot_models_provider() -> HoneypotModelsProvider:
    """Return the default provider — composition root for honeypot ORM models.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
