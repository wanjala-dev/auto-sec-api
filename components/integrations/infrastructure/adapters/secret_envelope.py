"""Fernet envelope for integrations secrets (Slack tokens, GitHub PATs).

The ONE encryption envelope for every secret column in the integrations
persistence app (``SinkConnector.secret_ciphertext``,
``GitHubConnection.token_ciphertext``). Uses Fernet (AES128 + HMAC) derived
from the project SECRET_KEY — same derivation as the payments envelope
(``components/payments/infrastructure/adapters/encryption.py``), kept
per-context because cross-context infrastructure imports are forbidden.

NOTE: key derivation is ``SHA256(settings.SECRET_KEY)``. Rotating the Django
SECRET_KEY permanently invalidates every stored ciphertext. Decrypt failures
are surfaced loudly (never silently returned as blank) so a key mismatch is an
operator-visible error, not a mystery 401 from GitHub.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

logger = logging.getLogger(__name__)


class SecretDecryptionError(RuntimeError):
    """A non-blank ciphertext could not be decrypted (key rotation/corruption)."""


def _derive_fernet_key() -> bytes:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_cipher() -> Fernet:
    return Fernet(_derive_fernet_key())


@sensitive_variables("plaintext")
def encrypt_secret(plaintext: str | None) -> str:
    """Encrypt a secret string; blank in → blank out (nothing to store)."""
    if not plaintext:
        return ""
    return _get_cipher().encrypt(plaintext.encode("utf-8")).decode("utf-8")


@sensitive_variables("ciphertext", "raw")
def decrypt_secret(ciphertext: str | None) -> str:
    """Decrypt a stored secret. Blank ciphertext (legacy/empty row) → "".

    Raises :class:`SecretDecryptionError` for any non-blank ciphertext that
    fails to decrypt — the caller must fail fast, not proceed with a blank
    credential.
    """
    if not ciphertext:
        return ""
    try:
        raw = _get_cipher().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        logger.error("integrations.secret_envelope.decrypt_failed reason=invalid_token")
        raise SecretDecryptionError(
            "Stored integration secret could not be decrypted. The encryption "
            "key may have changed; restore SECRET_KEY or re-save the secret."
        ) from exc
    return raw.decode("utf-8")
