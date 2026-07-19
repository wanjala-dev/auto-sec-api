"""Application-layer facade exposing feature flags to other contexts.

This facade re-exports shared_platform feature flag utilities, allowing other
contexts to use them without directly importing from the infrastructure layer.
"""

from components.shared_platform.infrastructure.services.feature_flags import (
    FeatureFlagEvaluation,
    bump_feature_flags_version,
    resolve_workspace_id_from_request,
    evaluate_feature_flag,
    is_feature_enabled,
    flags_for_context,
)

__all__ = [
    "FeatureFlagEvaluation",
    "bump_feature_flags_version",
    "resolve_workspace_id_from_request",
    "evaluate_feature_flag",
    "is_feature_enabled",
    "flags_for_context",
]
