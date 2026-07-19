"""Unit tests for RequestPresignedUploadUseCase.

Tests the in-memory contract: given a fake URL provider and a fake
file repository, the use case allocates a File row, signs the key,
and returns ``PresignedUploadResult``. Failures (disabled provider,
disallowed MIME) return ``PresignedUploadFailure`` with the right
status_code.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from components.shared_platform.application.commands.request_presigned_upload_command import (
    PresignedUploadFailure,
    PresignedUploadResult,
    RequestPresignedUploadCommand,
)
from components.shared_platform.application.use_cases.request_presigned_upload_use_case import (
    RequestPresignedUploadUseCase,
    _sanitize_filename,
)
from components.shared_platform.domain.entities.file_entity import FileEntity


class _InMemoryFileRepo:
    """Test fake — implements the subset of FileRepositoryPort the
    use case actually calls."""

    def __init__(self):
        self.created: list[dict] = []
        self._next_id = 1

    def create_for_external_upload(
        self, *, owner_id, workspace_id, storage_key, file_type
    ):
        record = {
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "storage_key": storage_key,
            "file_type": file_type,
        }
        self.created.append(record)
        entity = FileEntity(
            id=self._next_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
            file_path=storage_key,
            file_type=file_type,
            processing_status="pending",
            processing_error=None,
            processed_at=None,
            created=datetime(2026, 6, 7, 0, 0, 0),
        )
        self._next_id += 1
        return entity

    # Methods the use case does not call — stubs satisfy the ABC if
    # the use case ever drifts to call them.
    def create(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def find_by_id(self, file_id):  # pragma: no cover
        return None

    def update_processing_status(self, file_id, status):  # pragma: no cover
        pass

    def get_absolute_file_url(self, file_id, *, request=None):  # pragma: no cover
        return None


class _FakePresignedUrlProvider:
    """Records what was signed and returns a deterministic URL.

    The real adapter wraps boto3; this fake makes the use case
    testable without AWS or moto."""

    def __init__(self, *, enabled=True, ttl=900):
        self._enabled = enabled
        self._ttl = ttl
        self.signed_keys: list[str] = []

    @property
    def enabled(self):
        return self._enabled

    def generate_put_url(self, *, key):
        self.signed_keys.append(key)
        return f"https://example-bucket.s3.amazonaws.com/{key}?signed=yes"

    @property
    def presigned_ttl_seconds(self):
        return self._ttl


@pytest.fixture
def owner_id():
    return uuid4()


@pytest.fixture
def workspace_id():
    return "ws-123"


class TestRequestPresignedUploadUseCaseSuccess:
    def test_image_upload_creates_file_row_and_signs_key(
        self, owner_id, workspace_id
    ):
        repo = _InMemoryFileRepo()
        provider = _FakePresignedUrlProvider()
        use_case = RequestPresignedUploadUseCase(
            file_repo=repo, presigned_url_provider=provider
        )

        result = use_case.execute(
            RequestPresignedUploadCommand(
                owner_id=owner_id,
                workspace_id=workspace_id,
                filename="Family Photo.jpeg",
                content_type="image/jpeg",
            )
        )

        assert isinstance(result, PresignedUploadResult)
        assert result.file_id == 1
        assert result.key.startswith("uploads/")
        assert result.key.endswith(".jpeg")
        assert "Family-Photo" in result.key  # sanitized stem
        assert result.expires_in == 900
        assert result.put_url.endswith("?signed=yes")

        # File row was allocated with the same key the URL was signed for.
        assert len(repo.created) == 1
        assert repo.created[0]["storage_key"] == result.key
        assert repo.created[0]["owner_id"] == owner_id
        assert repo.created[0]["workspace_id"] == workspace_id
        assert repo.created[0]["file_type"] == "image"

        assert provider.signed_keys == [result.key]

    def test_key_is_uuid_namespaced_for_collision_safety(
        self, owner_id, workspace_id
    ):
        """Two uploads of the same filename must produce distinct keys."""
        repo = _InMemoryFileRepo()
        provider = _FakePresignedUrlProvider()
        use_case = RequestPresignedUploadUseCase(
            file_repo=repo, presigned_url_provider=provider
        )

        cmd = RequestPresignedUploadCommand(
            owner_id=owner_id,
            workspace_id=workspace_id,
            filename="photo.jpg",
            content_type="image/jpeg",
        )

        first = use_case.execute(cmd)
        second = use_case.execute(cmd)

        assert isinstance(first, PresignedUploadResult)
        assert isinstance(second, PresignedUploadResult)
        assert first.key != second.key

    def test_pdf_upload_classified_correctly(self, owner_id, workspace_id):
        repo = _InMemoryFileRepo()
        provider = _FakePresignedUrlProvider()
        use_case = RequestPresignedUploadUseCase(
            file_repo=repo, presigned_url_provider=provider
        )

        result = use_case.execute(
            RequestPresignedUploadCommand(
                owner_id=owner_id,
                workspace_id=workspace_id,
                filename="receipt.pdf",
                content_type="application/pdf",
            )
        )

        assert isinstance(result, PresignedUploadResult)
        assert repo.created[0]["file_type"] == "pdf"


class TestRequestPresignedUploadUseCaseFailure:
    def test_disabled_provider_returns_503(self, owner_id, workspace_id):
        """Local-dev fallback: when the storage backend is not S3-backed,
        the controller returns 503 so the frontend falls back to the
        multipart endpoint."""
        repo = _InMemoryFileRepo()
        provider = _FakePresignedUrlProvider(enabled=False)
        use_case = RequestPresignedUploadUseCase(
            file_repo=repo, presigned_url_provider=provider
        )

        result = use_case.execute(
            RequestPresignedUploadCommand(
                owner_id=owner_id,
                workspace_id=workspace_id,
                filename="photo.jpg",
                content_type="image/jpeg",
            )
        )

        assert isinstance(result, PresignedUploadFailure)
        assert result.status_code == 503
        assert "multipart" in result.message.lower()
        # Must NOT create an orphan File row when the provider is disabled.
        assert repo.created == []
        assert provider.signed_keys == []

    def test_disallowed_mime_returns_415(self, owner_id, workspace_id):
        """Executable / unknown MIME types must be rejected."""
        repo = _InMemoryFileRepo()
        provider = _FakePresignedUrlProvider()
        use_case = RequestPresignedUploadUseCase(
            file_repo=repo, presigned_url_provider=provider
        )

        result = use_case.execute(
            RequestPresignedUploadCommand(
                owner_id=owner_id,
                workspace_id=workspace_id,
                filename="malware.exe",
                content_type="application/x-msdownload",
            )
        )

        assert isinstance(result, PresignedUploadFailure)
        assert result.status_code == 415
        assert repo.created == []


class TestSanitizeFilename:
    """Direct unit tests on the helper — these run pure-Python without
    fixtures so a regression shows up as a 1-line failure."""

    def test_spaces_become_dashes(self):
        assert _sanitize_filename("My Photo.jpg") == "My-Photo.jpg"

    def test_unicode_is_stripped(self):
        # Café → "Caf" — sanitiser keeps only [A-Za-z0-9._-].
        out = _sanitize_filename("Café.png")
        assert out == "Caf-.png" or out == "Caf.png"

    def test_no_extension_defaults_to_upload(self):
        assert _sanitize_filename("") == "upload"

    def test_long_stem_truncated(self):
        long_name = "a" * 200 + ".jpg"
        out = _sanitize_filename(long_name)
        assert len(out) <= 72  # 64 stem + 4 ext + slack
        assert out.endswith(".jpg")

    def test_extension_lowercased(self):
        assert _sanitize_filename("photo.JPEG").endswith(".jpeg")
