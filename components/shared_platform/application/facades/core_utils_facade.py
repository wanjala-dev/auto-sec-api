"""Application-layer facade exposing core utilities to other contexts.

This facade re-exports shared_platform infrastructure utilities, allowing other
contexts to use them without directly importing from the infrastructure layer.
"""

from components.shared_platform.infrastructure.services.core_utils import (
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
]
