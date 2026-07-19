"""Provider for ORM model classes from ``infrastructure.persistence.core``.

Controllers MUST NOT import ORM model classes from
``infrastructure.persistence.core.*`` directly — Explicit Architecture forbids
controller-to-infrastructure imports at module top. This provider exposes the
models via lazy properties so that the model classes are imported only when
the controller call site asks for them at request time.

Usage from a controller::

    from components.shared_platform.application.providers.core_models_provider import (
        get_core_models_provider,
    )

    FeatureFlag = get_core_models_provider().FeatureFlag

    flag = FeatureFlag.objects.filter(key="feature.resource_sharing").first()

New models in ``infrastructure.persistence.core`` that controllers need MUST
be added here as additional ``@property`` lookups — keep this file as the
single entry point.
"""

from __future__ import annotations

from typing import Any, Protocol


class CoreModelsProviderProtocol(Protocol):
    """Structural type for the core models provider.

    Exists so call sites can type-hint against the protocol (no Django import)
    in their own annotations without dragging the ORM into the application
    layer's type space.
    """

    @property
    def FeatureFlag(self) -> Any:  # noqa: N802 — mirrors ORM class name
        ...


class CoreModelsProvider:
    """Façade exposing core persistence ORM model classes via lazy properties.

    Every property performs the ``from infrastructure.persistence.core...models
    import X`` inside its body so the import graph at module-load time stays
    framework-free.
    """

    @property
    def FeatureFlag(self) -> Any:  # noqa: N802 — mirrors ORM class name
        from infrastructure.persistence.core.models import FeatureFlag

        return FeatureFlag


_default = CoreModelsProvider()


def get_core_models_provider() -> CoreModelsProvider:
    """Return the default :class:`CoreModelsProvider` instance.

    Tests may monkeypatch this module's ``_default`` attribute (or override
    ``get_core_models_provider`` itself) to swap in fakes/stubs.
    """
    return _default
