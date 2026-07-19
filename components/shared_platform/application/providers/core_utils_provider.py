"""Provider/composition root for core_utils (HTTP responses, comments, URLs).

Controllers MUST consume :class:`CoreUtilsProvider` instead of
importing ``components.shared_platform.infrastructure.services.core_utils``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

Every method lazy-imports the underlying helper so module load stays free
of Django/DRF/PIL imports and tests can monkeypatch individual methods.
"""

from __future__ import annotations

from typing import Any


class CoreUtilsProvider:
    """Driving-side façade for shared response/url/email/comment helpers."""

    def success_response(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            success_response as _success_response,
        )

        return _success_response(*args, **kwargs)

    def error_response(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            error_response as _error_response,
        )

        return _error_response(*args, **kwargs)

    def get_comments(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            get_comments as _get_comments,
        )

        return _get_comments(*args, **kwargs)

    def resolve_frontend_base_url(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            resolve_frontend_base_url as _resolve_frontend_base_url,
        )

        return _resolve_frontend_base_url(*args, **kwargs)

    def build_absolute_media_url(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            build_absolute_media_url as _build_absolute_media_url,
        )

        return _build_absolute_media_url(*args, **kwargs)

    def generate_random_string(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            generate_random_string as _generate_random_string,
        )

        return _generate_random_string(*args, **kwargs)

    def generate_password(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            generate_password as _generate_password,
        )

        return _generate_password(*args, **kwargs)

    def send_email(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.core_utils import (
            send_email as _send_email,
        )

        return _send_email(*args, **kwargs)


_default = CoreUtilsProvider()


def get_core_utils_provider() -> CoreUtilsProvider:
    """Return the default provider — composition root for core_utils helpers.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
