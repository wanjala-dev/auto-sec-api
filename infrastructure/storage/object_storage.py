"""Canonical boto3 client factory for object storage (S3 / MinIO).

**Every** object-storage client in this codebase is built here, so that the one
setting that is catastrophic to get wrong is impossible to forget: the signature
version.

## Why this module exists

botocore does **not** default to SigV4 when presigning against a client built with
an explicit ``endpoint_url`` — it mints a legacy **SigV2** URL
(``?AWSAccessKeyId=…&Signature=…&Expires=…``). That is not a cosmetic difference:

* **SigV2 folds ``Content-Type`` into the signed string.** SigV4 presigned URLs sign
  only ``host``. So a SigV2 presigned PUT is invalidated by the client merely
  *sending* a ``Content-Type`` header — which every uploader does. Measured against
  our own MinIO (``RELEASE.2025-09-07T16-13-09Z``):

  | presign | request | result |
  |---|---|---|
  | SigV2 | ``PUT`` bare | 200 |
  | SigV2 | ``PUT`` + ``Content-Type`` | **403 SignatureDoesNotMatch** |
  | SigV4 | ``PUT`` + ``Content-Type`` | 200 |

  This is the defect ADR 0022's scan-artifact upload hit live in #311: a
  perfectly-formed request, rejected, with every unit and integration test green.
* **AWS regions launched after January 2014 do not support SigV2 at all.** A SigV2
  presign against them fails outright. Any migration of this storage from MinIO onto
  real S3 would break every presigned URL that is not SigV4.
* MinIO has SigV2 deprecated and can remove it at any release.

A presigned URL is signed *material handed to a third party* — it fails in the
client, not in our process, so no amount of server-side testing catches it. Three
separate call sites shipped this defect independently (scan artifacts, SBOM
download, report download) because each one was written by mirroring the last. This
factory is the fix that stops a fourth: there is no correctly-configured client to
forget to copy, because there is only one way to build one.

Enforced by ``tests/architecture/test_object_storage_sigv4.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The only signature version this codebase may sign object-storage requests with.
# Referenced by the architecture fitness test — keep the name stable.
OBJECT_STORAGE_SIGNATURE_VERSION = "s3v4"


def build_object_storage_client(
    *,
    endpoint_url: str | None = None,
    region_name: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    session_token: str | None = None,
    addressing_style: str | None = None,
):
    """Build an S3 client that always signs with SigV4.

    Args:
        endpoint_url: MinIO / S3-compatible endpoint. ``None`` (or empty) means real
            AWS S3 reached through boto3's normal endpoint resolution.
        region_name: AWS region. Defaults to ``us-east-1`` when unset — MinIO ignores
            it, but SigV4 requires *some* region in the credential scope.
        access_key / secret_key: static credentials. When either is missing, boto3's
            default credential chain is used instead (instance role / IRSA in prod) —
            which is a supported deployment, not a misconfiguration.
        session_token: the third element of a temporary (assume-role) credential set.
            Required when reading a customer's bucket through their audit role.
        addressing_style: ``"virtual"`` or ``"path"``. Leave ``None`` for botocore's
            default, which correctly picks path-style for a custom endpoint (MinIO
            has no per-bucket DNS) and virtual-host style for real AWS S3. Only pass
            it when a bucket genuinely requires one, e.g. a bucket reached over an
            AWS-only endpoint.
    """
    import boto3
    from botocore.config import Config

    config_kwargs: dict = {"signature_version": OBJECT_STORAGE_SIGNATURE_VERSION}
    if addressing_style:
        config_kwargs["s3"] = {"addressing_style": addressing_style}

    client_kwargs: dict = {
        "service_name": "s3",
        "region_name": region_name or "us-east-1",
        "config": Config(**config_kwargs),
    }
    # Only pass an endpoint when there is one: an explicit ``endpoint_url=None`` is
    # equivalent, but passing the key at all makes "real AWS S3" look accidental.
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    # Partial static credentials are always a config error — fall back to the default
    # chain rather than half-authenticating with a key and no secret.
    if access_key and secret_key:
        client_kwargs["aws_access_key_id"] = access_key
        client_kwargs["aws_secret_access_key"] = secret_key
        # Only meaningful alongside a static pair — a session token identifies a
        # temporary assume-role credential set.
        if session_token:
            client_kwargs["aws_session_token"] = session_token

    return boto3.client(**client_kwargs)
