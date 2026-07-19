"""Behaviour tests for S3MediaStorage.

These are pure-Python class-level assertions -- they verify the
defaults the production setting RELIES ON to keep uploads inside
the `media/` prefix and away from the `backup/` prefix that shares
the same bucket. No real S3 access, no @pytest.mark.django_db, no
fixtures: a smoke test that catches drift on the four invariants
that matter for the IAM split.
"""
from __future__ import annotations

import pytest

from infrastructure.storage.backends import S3MediaStorage


class TestS3MediaStorageDefaults:
    """Class-level defaults must stay in lockstep with the IAM
    policy on the data bucket. Drift here is silent and dangerous:
    an upload landing under backup/ would be writable by the cron
    user and inherit its retention lifecycle.
    """

    def test_location_is_media_prefix(self) -> None:
        # Drift here would let an upload escape into the bucket root
        # alongside backup/postgres/ -- the EC2 instance role would
        # then be able to overwrite media objects via its backup
        # policy. The IAM split assumes this prefix is exactly "media".
        assert S3MediaStorage.location == "media"

    def test_does_not_overwrite_on_collision(self) -> None:
        # Django's upload_to=... handlers expect unique suffix
        # behaviour; flipping this would silently destroy older
        # uploads with the same logical key.
        assert S3MediaStorage.file_overwrite is False

    def test_default_acl_is_none(self) -> None:
        # The bucket has block-public-access enabled. Setting any
        # per-object ACL ("public-read", etc.) would raise an
        # AccessDenied at upload time -- explicit None keeps every
        # upload path private by default.
        assert S3MediaStorage.default_acl is None

    def test_querystring_auth_is_on(self) -> None:
        # Signed URLs are the only way to serve a private object
        # from this bucket. If a future PR flips this off, the
        # entire media surface goes 403 in the browser.
        assert S3MediaStorage.querystring_auth is True


class TestS3MediaStorageInheritance:
    def test_inherits_from_django_storages_s3_backend(self) -> None:
        # If django-storages ever renames the import path, our
        # production STORAGES dict in api/settings/prod.py points at
        # this class -- catching the rename here is much louder than
        # a 500 on the first upload after deploy.
        from storages.backends.s3boto3 import S3Boto3Storage

        assert issubclass(S3MediaStorage, S3Boto3Storage)
