"""Application service for the shared_platform bounded context.

Orchestration only – delegates to use cases for business logic.
This is the single orchestration entry point for the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.shared_platform.application.providers.shared_platform_provider import (
    SharedPlatformProvider,
)


@dataclass
class SharedPlatformService:
    """Application service for the shared_platform bounded context.

    Orchestration only – delegates to use cases for business logic.
    Handles file uploads, search, honeypot, landing pages, and broadcasts.
    """

    provider: SharedPlatformProvider = field(default_factory=SharedPlatformProvider)

    def process_file_upload(self, **kwargs):
        """Orchestrate file upload processing.

        Delegates to ProcessFileUploadUseCase.
        """
        use_case = self.provider.build_process_file_upload_use_case()
        return use_case.execute(**kwargs)

    def request_presigned_upload(self, command):
        """Issue a presigned PUT URL for direct browser → S3 upload.

        Delegates to RequestPresignedUploadUseCase. Returns either
        ``PresignedUploadResult`` (file_id + put_url + key) or
        ``PresignedUploadFailure`` (message + status_code) — the
        controller translates both to an HTTP response.
        """
        use_case = self.provider.build_request_presigned_upload_use_case()
        return use_case.execute(command)

    def confirm_presigned_upload(self, command):
        """The browser finished its presigned PUT — confirm, and when the
        command carries index intent, request indexing through the
        opt-in policy. Idempotent.
        """
        use_case = self.provider.build_confirm_presigned_upload_use_case()
        return use_case.execute(command)

    def request_document_index(self, command):
        """Explicitly index a library document (opt-in RAG entry).

        Delegates to RequestDocumentIndexUseCase — the single gate that
        enforces the per-workspace daily quota and the failure
        circuit-breaker.
        """
        use_case = self.provider.build_request_document_index_use_case()
        return use_case.execute(command)
