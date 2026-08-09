"""ADR 0021 P0a locks — the AWS golden master + the provider fitness functions.

The ``PostureProvider`` refactor threads the provider through scanner → ingest →
URN. The regression it must never introduce is a byte of drift in the EXISTING
AWS identity strings (``source`` / ``fingerprint`` / ``asset_urn`` / attributes):
the SSOT's finding identity is ``(workspace, source, fingerprint)`` and the URN
is the cross-pillar correlation key — drift orphans every existing AWS finding
and corrupts the graph spine. So the golden master asserts LITERAL strings, not
derived ones.

The fitness half makes the "one-word shortcut" structurally unwritable: the
normalizer may build identity ONLY through the provider registry — no
string-literal ``"aws"`` / ``"vercel"`` in ``_to_normalized`` or the scanner's
``scan``.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from components.cloud_posture.domain.posture_provider import (
    AWS_POSTURE_PROVIDER,
    VERCEL_POSTURE_PROVIDER,
    UnknownPostureProviderError,
    resolve_posture_provider,
)
from components.cloud_posture.domain.scan_targets import (
    InvalidVercelScanTargetError,
    validate_vercel_scan_target,
)
from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    _to_normalized,
    records_to_scan_result,
)

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_ocsf_sample.json"


def _records():
    return json.loads(_FIXTURE.read_text())


class TestAwsGoldenMaster:
    """Literal-value locks for the AWS identity strings (pre/post P0a byte-identical)."""

    def test_arn_bearing_record_identity_is_byte_identical(self):
        result = records_to_scan_result(_records())  # NO provider arg — the default path every legacy caller takes

        by_check = {f.attributes["check_id"]: f for f in result.findings}
        s3 = by_check["s3_bucket_public_access"]
        # Literal strings — never derived in the assertion.
        assert s3.source == "cloud_posture.prowler"
        assert s3.asset_urn == "arn:aws:s3:::mybucket"
        assert s3.fingerprint == "s3_bucket_public_access|123456789012|arn:aws:s3:::mybucket"
        assert s3.attributes == {
            "check_id": "s3_bucket_public_access",
            "account_id": "123456789012",
            "region": "us-east-1",
            "service": "s3",
            "resource_type": "AwsS3Bucket",
            "resource_name": "mybucket",
            "resource_uid": "arn:aws:s3:::mybucket",
            "finding_uid": "prowler-aws-s3_bucket_public_access-123456789012-us-east-1-mybucket",
            "check_status": "fail",
        }

        root = by_check["iam_root_mfa_enabled"]
        assert root.source == "cloud_posture.prowler"
        assert root.asset_urn == "arn:aws:iam::123456789012:root"
        assert root.fingerprint == "iam_root_mfa_enabled|123456789012|arn:aws:iam::123456789012:root"

    def test_account_fallback_record_identity_is_byte_identical(self):
        # A resource-less, account-level check falls back to the per-account URN.
        record = {
            "metadata": {"event_code": "account_maintain_current_contact_details"},
            "severity": "Medium",
            "status_code": "FAIL",
            "finding_info": {"uid": "u-acct-1", "title": "Maintain current contact details"},
            "resources": [],
            "cloud": {"account": {"uid": "123456789012"}, "region": "us-east-1"},
        }
        result = records_to_scan_result([record])
        finding = result.findings[0]
        assert finding.asset_urn == "urn:aws:account/123456789012"
        assert finding.fingerprint == "account_maintain_current_contact_details|123456789012|"


class TestProviderFitness:
    """The structural version of "the shortcut is unwritable" (ADR 0021 D1)."""

    def test_normalizer_builds_identity_only_via_the_provider(self):
        source = inspect.getsource(_to_normalized)
        assert not re.search(r'"(aws|vercel)"', source), (
            "_to_normalized must derive source/URN/fingerprint from the PostureProvider, "
            "never a provider string literal"
        )

    def test_scanner_builds_the_command_only_via_the_provider(self):
        source = inspect.getsource(ProwlerScanner.scan)
        assert "prowler aws" not in source and "prowler vercel" not in source
        assert not re.search(r'"(aws|vercel)"', source)

    def test_registry_default_is_aws_and_sources_are_locked(self):
        # Blank/None → AWS: every pre-ADR-0021 caller carries no provider param.
        assert resolve_posture_provider(None) is AWS_POSTURE_PROVIDER
        assert resolve_posture_provider("") is AWS_POSTURE_PROVIDER
        assert resolve_posture_provider("vercel") is VERCEL_POSTURE_PROVIDER
        # The deliberate source-string asymmetry (D1): AWS keeps its pre-existing
        # source; renaming it would orphan every existing finding. Do NOT "fix".
        assert AWS_POSTURE_PROVIDER.source == "cloud_posture.prowler"
        assert VERCEL_POSTURE_PROVIDER.source == "cloud_posture.prowler.vercel"
        assert AWS_POSTURE_PROVIDER.token == "aws"
        assert VERCEL_POSTURE_PROVIDER.token == "vercel"

    def test_unknown_provider_fails_closed(self):
        with pytest.raises(UnknownPostureProviderError):
            resolve_posture_provider("azure")


class TestVercelScanTarget:
    """The Vercel injection gate (D3): team ids/slugs only, blank REJECTED (consent)."""

    @pytest.mark.parametrize("team", ["team_abc123DEF456", "team_A1", "acme", "my-team-01", "a"])
    def test_accepts_wellformed_team_ids_and_slugs(self, team):
        assert validate_vercel_scan_target(team) == team

    @pytest.mark.parametrize(
        "team",
        [
            "",  # blank = Prowler auto-discovers EVERY team — a consent violation
            None,
            "team_",  # empty opaque part
            "Acme",  # slug must be lowercase
            "acme team",  # whitespace
            "acme;rm -rf /",  # shell metacharacters
            "$(curl evil)",
            "team_" + "x" * 80,  # overlong
            "-leading-dash",
        ],
    )
    def test_rejects_malformed_or_blank_teams(self, team):
        with pytest.raises(InvalidVercelScanTargetError):
            validate_vercel_scan_target(team)


class TestVercelCredentialEnv:
    def test_pins_the_team_unconditionally(self):
        env = VERCEL_POSTURE_PROVIDER.credential_env({"token": "vc_tok"}, "team_abc123")
        assert env == {"VERCEL_TOKEN": "vc_tok", "VERCEL_TEAM": "team_abc123"}

    def test_missing_token_fails_fast(self):
        with pytest.raises(ValueError):
            VERCEL_POSTURE_PROVIDER.credential_env({}, "team_abc123")
        with pytest.raises(ValueError):
            VERCEL_POSTURE_PROVIDER.credential_env(None, "team_abc123")

    def test_aws_credential_env_is_byte_identical(self):
        env = AWS_POSTURE_PROVIDER.credential_env(
            {"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"}, "123456789012"
        )
        assert env == {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "y", "AWS_SESSION_TOKEN": "z"}
        assert AWS_POSTURE_PROVIDER.credential_env(None, "123456789012") == {}
