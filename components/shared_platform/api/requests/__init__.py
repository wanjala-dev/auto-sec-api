"""Request DTOs for shared_platform component."""

from .broadcast_requests import CreateBannerRequest, UpdateBannerRequest
from .uploads_requests import (
    CreateFileUploadRequest,
    DeleteFileUploadRequest,
    UpdateFileUploadRequest,
)

__all__ = [
    # Broadcast
    "CreateBannerRequest",
    "UpdateBannerRequest",
    # Uploads
    "CreateFileUploadRequest",
    "UpdateFileUploadRequest",
    "DeleteFileUploadRequest",
]
