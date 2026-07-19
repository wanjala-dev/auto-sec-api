"""Integration tests for ``POST /upload/presigned-put/``.

We patch ``S3PresignedUploadUrlAdapter.generate_put_url`` so the
endpoint exercises the full Django + DRF + use case chain without
touching boto3. boto3 itself is unit-tested by AWS; what's worth
testing here is the request validation + the controller-to-use-case
plumbing + the response shape the frontend depends on.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.fixture
def patched_provider():
    """Patch the adapter so ``enabled`` is True and ``generate_put_url``
    returns a deterministic URL — no AWS calls."""
    with patch(
        "components.shared_platform.application.providers.shared_platform_provider"
        ".S3PresignedUploadUrlAdapter"
    ) as adapter_class:
        adapter = adapter_class.return_value
        adapter.enabled = True
        adapter.presigned_ttl_seconds = 900
        adapter.generate_put_url.side_effect = (
            lambda *, key: f"https://example-bucket.s3.amazonaws.com/{key}?signed"
        )
        yield adapter


@pytest.mark.django_db
class TestPresignedPutUploadEndpoint:
    def test_authenticated_user_gets_signed_url(
        self, api_client, user_factory, workspace_factory, patched_provider
    ):
        user = user_factory()
        workspace = workspace_factory()
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("upload-presigned-put"),
            data={
                "filename": "Family Photo.jpeg",
                "content_type": "image/jpeg",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        body = response.json()
        assert "put_url" in body
        assert "key" in body
        assert "file_id" in body
        assert body["expires_in"] == 900
        assert body["key"].startswith("uploads/")
        assert body["key"].endswith(".jpeg")
        assert "Family-Photo" in body["key"]
        assert body["put_url"].endswith("?signed")

    def test_anonymous_user_is_rejected(
        self, api_client, workspace_factory, patched_provider
    ):
        workspace = workspace_factory()
        response = api_client.post(
            reverse("upload-presigned-put"),
            data={
                "filename": "photo.jpg",
                "content_type": "image/jpeg",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )
        assert response.status_code in (401, 403)

    def test_missing_filename_returns_400(
        self, api_client, user_factory, workspace_factory, patched_provider
    ):
        user = user_factory()
        workspace = workspace_factory()
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("upload-presigned-put"),
            data={
                "content_type": "image/jpeg",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )
        assert response.status_code == 400
        assert "filename" in response.json()["message"]

    def test_missing_workspace_id_returns_400(
        self, api_client, user_factory, patched_provider
    ):
        user = user_factory()
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("upload-presigned-put"),
            data={"filename": "x.jpg", "content_type": "image/jpeg"},
            format="json",
        )
        assert response.status_code == 400
        assert "workspace_id" in response.json()["message"]

    def test_disallowed_mime_returns_415(
        self, api_client, user_factory, workspace_factory, patched_provider
    ):
        user = user_factory()
        workspace = workspace_factory()
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("upload-presigned-put"),
            data={
                "filename": "malware.exe",
                "content_type": "application/x-msdownload",
                "workspace_id": str(workspace.id),
            },
            format="json",
        )
        assert response.status_code == 415

    def test_disabled_provider_returns_503(
        self, api_client, user_factory, workspace_factory
    ):
        """Local dev fallback path — when the adapter is disabled,
        the controller surfaces 503 and the frontend falls back to the
        multipart endpoint."""
        with patch(
            "components.shared_platform.application.providers.shared_platform_provider"
            ".S3PresignedUploadUrlAdapter"
        ) as adapter_class:
            adapter = adapter_class.return_value
            adapter.enabled = False
            adapter.presigned_ttl_seconds = 900

            user = user_factory()
            workspace = workspace_factory()
            api_client.force_authenticate(user=user)

            response = api_client.post(
                reverse("upload-presigned-put"),
                data={
                    "filename": "photo.jpg",
                    "content_type": "image/jpeg",
                    "workspace_id": str(workspace.id),
                },
                format="json",
            )

        assert response.status_code == 503
        assert "multipart" in response.json()["message"].lower()
