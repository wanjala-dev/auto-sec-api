"""Unit tests for the fix-code secret redactor (ADR 0012 P6, defence-in-depth)."""

from __future__ import annotations

import pytest

from components.remediation.domain.services.secret_redactor import (
    REDACTION_PLACEHOLDER,
    redact_secrets,
)

pytestmark = pytest.mark.unit


def test_redacts_aws_access_key():
    text = "client = boto3.client('s3', aws_access_key_id='AKIAIOSFODNN7EXAMPLE')"
    redacted, count = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert REDACTION_PLACEHOLDER in redacted
    assert count >= 1


def test_redacts_pem_private_key_block():
    text = (
        "KEY = '''-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0Z3VS5JJ\nc7mHR7pv\n-----END RSA PRIVATE KEY-----'''"
    )
    redacted, count = redact_secrets(text)
    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "MIIEowIBAAKCAQEA" not in redacted
    assert count == 1


def test_redacts_jwt_and_bearer_and_openai():
    text = (
        "token = eyJhbGciOiJIUzI1Ni2.eyJzdWIiOiIxMjM0NTY.SflKxwRJSMeKKF2QT4\n"
        "api_key = 'sk-abcdefghijklmnopqrstuvwxyz0123'"
    )
    redacted, count = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1Ni2" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in redacted
    assert count >= 2


def test_redacts_secret_assignment_keeps_key_name():
    text = 'password = "hunter2superSecret123"'
    redacted, count = redact_secrets(text)
    assert "hunter2superSecret123" not in redacted
    # the KEY name is preserved so the fix stays readable
    assert "password" in redacted
    assert REDACTION_PLACEHOLDER in redacted
    assert count == 1


def test_redacts_quoted_key_json_dict_secret():
    # JSON/dict-shaped secrets — the ``"`` between key and ``:`` used to break the
    # bare ``\bkey\b\s*[:=]`` match, so these leaked through unredacted.
    text = '{"api_key": "AbCdEf0123456789xyzLongEnough"}'
    redacted, count = redact_secrets(text)
    assert "AbCdEf0123456789xyzLongEnough" not in redacted
    assert REDACTION_PLACEHOLDER in redacted
    # the key name is preserved so the fix stays readable
    assert "api_key" in redacted
    assert count == 1


def test_redacts_single_quoted_dict_password():
    text = "config = {'password': 'sup3rSecretValue123'}"
    redacted, count = redact_secrets(text)
    assert "sup3rSecretValue123" not in redacted
    assert REDACTION_PLACEHOLDER in redacted
    assert "password" in redacted
    assert count == 1


def test_leaves_benign_code_untouched():
    text = "def add(a, b):\n    return a + b  # no secrets here\n"
    redacted, count = redact_secrets(text)
    assert redacted == text
    assert count == 0


def test_empty_input_is_noop():
    assert redact_secrets("") == ("", 0)
    assert redact_secrets(None) == ("", 0)  # type: ignore[arg-type]
