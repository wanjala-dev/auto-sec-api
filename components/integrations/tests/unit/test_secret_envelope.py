"""Unit tests — integrations Fernet secret envelope (no DB)."""

from __future__ import annotations

import pytest

from components.integrations.application.providers.secret_envelope_provider import (
    decrypt_secret,
    encrypt_secret,
    get_secret_decryption_error,
)


@pytest.mark.unit
class TestSecretEnvelope:
    def test_round_trip(self):
        ciphertext = encrypt_secret("ghp_example_fine_grained_pat")
        assert ciphertext
        assert ciphertext != "ghp_example_fine_grained_pat"
        assert decrypt_secret(ciphertext) == "ghp_example_fine_grained_pat"

    def test_blank_in_blank_out(self):
        assert encrypt_secret("") == ""
        assert encrypt_secret(None) == ""
        assert decrypt_secret("") == ""
        assert decrypt_secret(None) == ""

    def test_corrupted_ciphertext_fails_loudly(self):
        error_type = get_secret_decryption_error()
        with pytest.raises(error_type):
            decrypt_secret("not-a-fernet-token")

    def test_ciphertext_never_contains_plaintext(self):
        secret = "ghp_super_secret_token_value"
        assert secret not in encrypt_secret(secret)
