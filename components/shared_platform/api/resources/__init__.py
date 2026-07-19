"""Resource DTOs for shared_platform component."""

from .broadcast_resources import BannerCollectionResource, BannerResource
from .uploads_resources import FileUploadCollectionResource, FileUploadResource

__all__ = [
    # Broadcast
    "BannerResource",
    "BannerCollectionResource",
    # Uploads
    "FileUploadResource",
    "FileUploadCollectionResource",
]
