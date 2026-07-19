"""Provider/composition root for feature flag evaluation.

Controllers and permissions MUST consume :class:`FeatureFlagsProvider`
instead of importing
``components.shared_platform.infrastructure.services.feature_flags`` directly.
The arch test ``test_controllers_do_not_import_concrete_adapters`` enforces
this.

A thin application-layer facade already re-exports the same functions for
intra-application use; this provider is the controller-facing equivalent
that keeps the import graph free of infrastructure imports and is fully
lazy.
"""

from __future__ import annotations

from typing import Any


class FeatureFlagsProvider:
    """Driving-side façade for the feature-flag evaluation service."""

    def is_feature_enabled(self, *args: Any, **kwargs: Any) -> bool:
        from components.shared_platform.infrastructure.services.feature_flags import (
            is_feature_enabled as _is_feature_enabled,
        )

        return _is_feature_enabled(*args, **kwargs)

    def evaluate_feature_flag(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.feature_flags import (
            evaluate_feature_flag as _evaluate_feature_flag,
        )

        return _evaluate_feature_flag(*args, **kwargs)

    def flags_for_context(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.feature_flags import (
            flags_for_context as _flags_for_context,
        )

        return _flags_for_context(*args, **kwargs)

    def resolve_workspace_id_from_request(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.feature_flags import (
            resolve_workspace_id_from_request as _resolve_workspace_id_from_request,
        )

        return _resolve_workspace_id_from_request(*args, **kwargs)

    def bump_feature_flags_version(self) -> int:
        from components.shared_platform.infrastructure.services.feature_flags import (
            bump_feature_flags_version as _bump_feature_flags_version,
        )

        return _bump_feature_flags_version()


_default = FeatureFlagsProvider()


def get_feature_flags_provider() -> FeatureFlagsProvider:
    """Return the default provider — composition root for feature-flag evaluation.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
