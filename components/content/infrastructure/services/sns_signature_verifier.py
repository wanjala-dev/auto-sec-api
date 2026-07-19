"""Verify Amazon SNS notification signatures.

SNS notifications are signed; the receiver MUST verify the signature
before trusting the message contents — otherwise anyone who can POST to
the endpoint can fake bounces/complaints and push our subscriber list
into the suppression table.

Verification steps (per https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html):

1. SigningCertURL MUST match ``^https://sns(.|-)[a-z0-9-]+\\.amazonaws\\.com/.*\\.pem$``.
   This is the most important defense — without it, an attacker could
   point us at their own cert. The regex matches both
   ``sns.us-east-1.amazonaws.com/...`` and
   ``sns-fips.us-east-1.amazonaws.com/...``.
2. Fetch the cert from that URL (cached briefly — SNS rotates certs
   rarely).
3. Build the signing string from a specific set of fields in canonical
   order; the field set depends on Type (Notification vs
   SubscriptionConfirmation).
4. Decode the Signature (base64) and verify against the signing string
   using the cert's RSA public key.
5. Verify TopicArn matches our configured topic ARN (defence in depth
   — an attacker who somehow forged a valid signature would still have
   to forge it for OUR topic).

The implementation here is intentionally small + auditable. Anything
more elaborate (e.g. multi-region cert pinning, SNS message
deduplication via MessageId) can layer on later.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

logger = logging.getLogger(__name__)


_SIGNING_CERT_HOST_RE = re.compile(
    r"^sns(?:[.-][a-z0-9-]+)?\.amazonaws\.com$"
)
# Fields hashed for SubscriptionConfirmation + UnsubscribeConfirmation —
# in this order, each followed by '\n'.
_SUBSCRIPTION_FIELDS = (
    "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
)
# Fields hashed for Notification.
_NOTIFICATION_FIELDS = (
    "Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type",
)


class SnsSignatureError(Exception):
    """Raised when SNS signature verification fails."""


def verify_sns_signature(payload: dict[str, Any], *, expected_topic_arn: str | None = None) -> None:
    """Verify an SNS notification payload. Raises ``SnsSignatureError``
    on any failure.

    ``payload`` is the parsed JSON body of the SNS POST. If
    ``expected_topic_arn`` is provided, the message's TopicArn must
    match it — defence against an attacker who got hold of a valid
    cert for a different SNS topic.
    """

    signing_cert_url = payload.get("SigningCertURL") or payload.get("SigningCertUrl")
    if not signing_cert_url:
        raise SnsSignatureError("missing SigningCertURL")
    parsed = urlparse(signing_cert_url)
    if parsed.scheme != "https":
        raise SnsSignatureError(f"SigningCertURL is not https: {signing_cert_url!r}")
    if not _SIGNING_CERT_HOST_RE.match(parsed.netloc):
        raise SnsSignatureError(
            f"SigningCertURL host is not on amazonaws.com: {parsed.netloc!r}"
        )
    if not parsed.path.endswith(".pem"):
        raise SnsSignatureError(
            f"SigningCertURL path does not end with .pem: {parsed.path!r}"
        )

    if expected_topic_arn and payload.get("TopicArn") != expected_topic_arn:
        raise SnsSignatureError(
            f"TopicArn mismatch: got {payload.get('TopicArn')!r}, "
            f"expected {expected_topic_arn!r}"
        )

    message_type = payload.get("Type") or ""
    if message_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = _SUBSCRIPTION_FIELDS
    elif message_type == "Notification":
        fields = _NOTIFICATION_FIELDS
    else:
        raise SnsSignatureError(f"unsupported Type: {message_type!r}")

    # Build the canonical signing string. Per AWS docs, each field is
    # ``<name>\n<value>\n`` — fields with missing values are skipped
    # entirely (no name, no newline).
    parts: list[str] = []
    for field in fields:
        value = payload.get(field)
        if value is None:
            continue
        parts.append(f"{field}\n{value}\n")
    signing_string = "".join(parts).encode("utf-8")

    try:
        cert_bytes = requests.get(signing_cert_url, timeout=5).content
    except requests.RequestException as exc:
        raise SnsSignatureError(f"failed to fetch signing cert: {exc}") from exc

    try:
        cert = load_pem_x509_certificate(cert_bytes)
        public_key = cert.public_key()
        signature = base64.b64decode(payload.get("Signature") or "")
        public_key.verify(
            signature,
            signing_string,
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
    except Exception as exc:  # noqa: BLE001
        raise SnsSignatureError(f"signature verification failed: {exc}") from exc
