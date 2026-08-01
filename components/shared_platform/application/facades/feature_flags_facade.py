"""Application-layer facade exposing feature flags to other contexts.

This facade re-exports shared_platform feature flag utilities, allowing other
contexts to use them without directly importing from the infrastructure layer.
"""

from components.shared_platform.infrastructure.services.feature_flags import (
    FeatureFlagEvaluation,
    bump_feature_flags_version,
    evaluate_feature_flag,
    flags_for_context,
    is_feature_enabled,
    resolve_workspace_id_from_request,
    set_workspace_flag,
)

__all__ = [
    "FeatureFlagEvaluation",
    "bump_feature_flags_version",
    "evaluate_feature_flag",
    "flags_for_context",
    "is_feature_enabled",
    "resolve_workspace_id_from_request",
    "set_workspace_flag",
]
