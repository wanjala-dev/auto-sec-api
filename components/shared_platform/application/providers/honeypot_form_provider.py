"""Provider/composition root for the admin honeypot login form.

Controllers MUST consume :class:`HoneypotFormProvider` instead of
importing
``components.shared_platform.infrastructure.services.honeypot_forms``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.
"""

from __future__ import annotations

from typing import Any


class HoneypotFormProvider:
    """Driving-side façade for the honeypot authentication form."""

    def get_form_class(self) -> Any:
        from components.shared_platform.infrastructure.services.honeypot_forms import (
            HoneypotAuthenticationForm,
        )

        return HoneypotAuthenticationForm


_default = HoneypotFormProvider()


def get_honeypot_form_provider() -> HoneypotFormProvider:
    """Return the default provider — composition root for the honeypot form.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
