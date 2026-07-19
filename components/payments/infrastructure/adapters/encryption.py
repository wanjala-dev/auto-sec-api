"""
Lightweight helpers to encrypt/decrypt payment secrets.

Uses Fernet (AES128 + HMAC) derived from the project SECRET_KEY so we can store
provider credentials encrypted at rest. The helpers accept dictionaries and
return strings that can be persisted in text fields.

NOTE: The current key derivation is `SHA256(settings.SECRET_KEY)`. Rotating the
Django SECRET_KEY will permanently invalidate every encrypted credential blob.
A KMS-backed key with explicit versioning is the long-term fix; tracking that
as a separate task. Until then, decrypt failures are surfaced loudly so ops
can detect a key mismatch immediately rather than silently returning {}.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


class PaymentCredentialDecryptionError(RuntimeError):
    """Raised when an encrypted credential blob cannot be decrypted.

    This usually means the encryption key has rotated (e.g. SECRET_KEY change)
    or the stored ciphertext is corrupted. Either way, the caller cannot proceed
    safely — silently returning an empty dict would mask a configuration outage.
    """


def _derive_fernet_key() -> bytes:
    """
    Derive a 32-byte key from Django's SECRET_KEY. We hash the secret key to
    produce a deterministic, Fernet-compatible key.
    """
    secret = settings.SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    return base64.urlsafe_b64encode(digest)


def _get_cipher() -> Fernet:
    return Fernet(_derive_fernet_key())


def encrypt_json(payload: dict[str, Any] | None) -> str:
    """
    Serialize the supplied mapping and return an encrypted string. Returns an
    empty string when there is no payload so callers can store blank values.
    """
    if not payload:
        return ""
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    return _get_cipher().encrypt(data).decode("utf-8")


def decrypt_json(token: str) -> dict[str, Any]:
    """
    Decrypt the supplied string and load the JSON payload.

    Returns an empty dict only when the token is itself blank (legacy/empty
    rows). For any non-blank token that fails to decrypt, raises
    ``PaymentCredentialDecryptionError`` so the caller fails fast and the
    operator sees a real error in logs instead of a downstream
    ``ImproperlyConfigured("Stripe secret key is required")`` mystery.
    """
    if not token:
        return {}
    try:
        data = _get_cipher().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        logger.error(
            "payments.encryption.decrypt_failed reason=invalid_token "
            "(SECRET_KEY rotation or corrupted ciphertext)"
        )
        raise PaymentCredentialDecryptionError(
            "Stored payment credentials could not be decrypted. The encryption "
            "key may have changed; rotate or restore SECRET_KEY, then re-save "
            "the credentials."
        ) from exc
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("payments.encryption.decrypt_failed reason=json_decode")
        raise PaymentCredentialDecryptionError(
            "Decrypted payment credentials are not valid JSON."
        ) from exc
