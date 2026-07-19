"""Provider/composition root for core_validators (UUID + payload helpers).

Controllers MUST consume :class:`CoreValidatorsProvider` instead of
importing ``components.shared_platform.infrastructure.services.core_validators``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the validator so module load is cheap and tests
can monkeypatch ``provider.ensure_uuid`` without dragging Django/DRF in at
import time.
"""

from __future__ import annotations

from typing import Any


class CoreValidatorsProvider:
    """Driving-side façade for shared validator utilities."""

    def ensure_uuid(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_validators import (
            ensure_uuid as _ensure_uuid,
        )

        return _ensure_uuid(*args, **kwargs)


_default = CoreValidatorsProvider()


def get_core_validators_provider() -> CoreValidatorsProvider:
    """Return the default provider — composition root for core_validators.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
