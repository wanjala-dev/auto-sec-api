"""Application-layer façade for the integrations Fernet secret envelope.

The ONE entry point application code (and callers in other contexts' allowed
layers) uses to encrypt/decrypt integrations secrets — ``SinkConnector``
tokens and ``GitHubConnection`` PATs alike. Provider files are the only
application-layer slot allowed to touch own-context infrastructure (they are
the composition root), which keeps ``cryptography``/Django out of use cases.
"""

from __future__ import annotations


def encrypt_secret(plaintext: str | None) -> str:
    from components.integrations.infrastructure.adapters.secret_envelope import encrypt_secret as _encrypt

    return _encrypt(plaintext)


def decrypt_secret(ciphertext: str | None) -> str:
    """Decrypt a stored integrations secret.

    Raises ``SecretDecryptionError`` (import it from this module) when a
    non-blank ciphertext cannot be decrypted.
    """
    from components.integrations.infrastructure.adapters.secret_envelope import decrypt_secret as _decrypt

    return _decrypt(ciphertext)


def get_secret_decryption_error() -> type[Exception]:
    """The exception type raised on decrypt failure (lazy — keeps this module
    free of infrastructure imports at module load)."""
    from components.integrations.infrastructure.adapters.secret_envelope import SecretDecryptionError

    return SecretDecryptionError
