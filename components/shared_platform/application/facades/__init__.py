"""Application-layer facades for shared_platform context."""

from .core_utils_facade import (
    success_response,
    error_response,
    generate_random_string,
    generate_password,
    send_email,
    get_comments,
    build_absolute_media_url,
    build_image_variant,
    normalize_frontend_base,
    resolve_frontend_base_url,
)

from .feature_flags_facade import (
    FeatureFlagEvaluation,
    bump_feature_flags_version,
    resolve_workspace_id_from_request,
    evaluate_feature_flag,
    is_feature_enabled,
    flags_for_context,
)

__all__ = [
    "success_response",
    "error_response",
    "generate_random_string",
    "generate_password",
    "send_email",
    "get_comments",
    "build_absolute_media_url",
    "build_image_variant",
    "normalize_frontend_base",
    "resolve_frontend_base_url",
    "FeatureFlagEvaluation",
    "bump_feature_flags_version",
    "resolve_workspace_id_from_request",
    "evaluate_feature_flag",
    "is_feature_enabled",
    "flags_for_context",
]
