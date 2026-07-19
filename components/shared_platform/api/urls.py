"""Consolidated URL routing for shared_platform component.

This module consolidates URL patterns from:
- broadcast_urls: Banner endpoints
- core_urls: Feature flags endpoints
- honeypot_urls: Admin honeypot endpoints
- uploads_urls: File upload endpoints
- document imports: shared document-import pipeline endpoints

Pattern lists are exported separately so root urls.py can include them individually.
"""

from django.urls import path
from rest_framework import routers

from components.shared_platform.api.controller import (
    # Broadcast
    BannerViewSet,
    DocumentIndexView,
    FeatureFlagStatusView,
    # Core
    FeatureFlagsView,
    # Uploads
    FileSerializerDetail,
    FileUploadView,
    # Honeypot
    HoneypotLoginView,
    PresignedPutUploadView,
    PresignedUploadConfirmView,
)
from components.shared_platform.api.document_import_controller import (
    DocumentImportApplyView,
    DocumentImportDetailView,
    DocumentImportListCreateView,
    DocumentImportRetryView,
    DocumentImportRowDetailView,
    DocumentImportRowListView,
)
from components.shared_platform.api.unified_documents_controller import (
    UnifiedDocumentListView,
)

# =============================================================================
# BROADCAST (ANNOUNCEMENTS) URLS
# =============================================================================

broadcast_router = routers.DefaultRouter()
broadcast_router.register(r"banners", BannerViewSet, basename="banner")

broadcast_urlpatterns = broadcast_router.urls


# =============================================================================
# CORE (FEATURE FLAGS) URLS
# =============================================================================

core_urlpatterns = [
    path("", FeatureFlagsView.as_view(), name="feature-flags"),
    path("<str:key>/", FeatureFlagStatusView.as_view(), name="feature-flag"),
]


# =============================================================================
# HONEYPOT (ADMIN DECOY) URLS
# =============================================================================

honeypot_urlpatterns = [
    path("", HoneypotLoginView.as_view(), name="login"),
]

# This namespace is set when including in root urls.py
honeypot_app_name = "admin_honeypot"


# =============================================================================
# UPLOADS (FILE MANAGEMENT) URLS
# =============================================================================

uploads_urlpatterns = [
    path(
        "",
        FileUploadView.as_view(
            {"get": "list", "post": "create", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="files_list",
    ),
    # Issue a presigned PUT URL so the browser uploads bytes directly
    # to S3 instead of streaming through Django. Falls back to the
    # multipart `` `` (root) endpoint above when storage isn't S3-backed.
    path("presigned-put/", PresignedPutUploadView.as_view(), name=PresignedPutUploadView.name),
    # Step 2: the browser PUT succeeded — confirm the bytes landed.
    # Indexing is opt-in: pass {index: true} (the AI-grounding uploader)
    # or call the explicit index endpoint below later.
    path("presigned-put/confirm/", PresignedUploadConfirmView.as_view(), name=PresignedUploadConfirmView.name),
    # Explicitly index a library document into the workspace RAG store
    # (opt-in; quota + circuit-breaker enforced; also the retry path).
    path("<int:file_id>/index/", DocumentIndexView.as_view(), name=DocumentIndexView.name),
    path("<int:pk>/", FileSerializerDetail.as_view(), name="file-detail-short"),
    path("upload/<int:pk>/", FileSerializerDetail.as_view(), name=FileSerializerDetail.name),
]


# =============================================================================
# DOCUMENT IMPORTS (SHARED PIPELINE) URLS
# =============================================================================

documents_urlpatterns = [
    path("", UnifiedDocumentListView.as_view(), name="unified-document-list"),
]

imports_urlpatterns = [
    path("", DocumentImportListCreateView.as_view(), name="document-import-list-create"),
    path("<int:import_id>/", DocumentImportDetailView.as_view(), name="document-import-detail"),
    path("<int:import_id>/rows/", DocumentImportRowListView.as_view(), name="document-import-row-list"),
    path(
        "<int:import_id>/rows/<int:row_id>/", DocumentImportRowDetailView.as_view(), name="document-import-row-detail"
    ),
    path("<int:import_id>/apply/", DocumentImportApplyView.as_view(), name="document-import-apply"),
    path("<int:import_id>/retry/", DocumentImportRetryView.as_view(), name="document-import-retry"),
]
