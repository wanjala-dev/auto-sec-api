"""Unit tests for the Trivy pillar (ADR 0006) — pure logic, no k8s, no trivy binary."""

from __future__ import annotations

import json

import pytest

from components.container_security.domain.image_reference import (
    InvalidImageReferenceError,
    validate_image_reference,
)
from components.container_security.infrastructure.adapters.trivy_scanner import TrivyScanner
from components.container_security.infrastructure.services.trivy_normalizer import (
    trivy_json_to_scan_result,
)
from components.scanning.application.ports.scan_execution_backend import (
    ScanJobResult,
    ScanJobSpec,
)
from components.shared_kernel.application.ports.scanner_port import ScanTarget
from components.shared_kernel.domain.security import Severity

pytestmark = pytest.mark.unit


# ── image-reference validator (the untrusted-input gate) ───────────────
class TestImageReferenceValidation:
    @pytest.mark.parametrize(
        "ref",
        [
            "nginx:latest",
            "nginx",
            "library/nginx:1.25",
            "ghcr.io/org/app:sha-abc",
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/repo:tag",
            "repo@sha256:" + "a" * 64,
        ],
    )
    def test_accepts_valid_refs(self, ref):
        assert validate_image_reference(ref) == ref

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "-oCVE.txt",  # arg/flag injection
            "--output=/etc/passwd",
            "nginx; rm -rf /",  # shell metachars
            "nginx:latest && curl evil",
            "nginx\n--bad",
            "a" * 600,  # too long
        ],
    )
    def test_rejects_malicious_refs(self, bad):
        with pytest.raises(InvalidImageReferenceError):
            validate_image_reference(bad)

    def test_registry_allowlist(self):
        ecr = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
        assert validate_image_reference(f"{ecr}/repo:tag", allowed_registries=[ecr])
        with pytest.raises(InvalidImageReferenceError):
            validate_image_reference("docker.io/evil/x:latest", allowed_registries=[ecr])
        with pytest.raises(InvalidImageReferenceError):
            validate_image_reference("nginx:latest", allowed_registries=[ecr])  # implicit hub


# ── Trivy JSON → NormalizedFinding ─────────────────────────────────────
_TRIVY_JSON = {
    "ArtifactName": "nginx:latest",
    "Results": [
        {
            "Target": "nginx:latest (debian 12.1)",
            "Class": "os-pkgs",
            "Type": "debian",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2023-1234",
                    "PkgName": "libssl3",
                    "InstalledVersion": "3.0.9-1",
                    "FixedVersion": "3.0.11-1",
                    "Severity": "HIGH",
                    "Title": "openssl: buffer overflow",
                    "Description": "A flaw...",
                    "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2023-1234",
                },
                {
                    "VulnerabilityID": "CVE-2022-9999",
                    "PkgName": "zlib",
                    "InstalledVersion": "1.2.13",
                    "FixedVersion": "",
                    "Severity": "UNKNOWN",
                    "Title": "",
                },
            ],
        },
        {"Target": "no-vulns", "Class": "lang-pkgs"},  # a result with no Vulnerabilities key
    ],
}


class TestTrivyNormalizer:
    def test_maps_vulnerabilities(self):
        result = trivy_json_to_scan_result(_TRIVY_JSON, image_ref="nginx:latest")
        assert result.engine == "trivy"
        assert len(result.findings) == 2
        assert result.failed_count == 2 and result.total_checks == 2

        high = next(f for f in result.findings if f.severity is Severity.HIGH)
        assert high.source == "container_security.trivy"
        assert high.fingerprint == "CVE-2023-1234|nginx:latest|libssl3|3.0.9-1"
        assert high.asset_urn == "urn:oci:nginx:latest"
        assert high.attributes["vulnerability_id"] == "CVE-2023-1234"
        assert high.attributes["fixed_version"] == "3.0.11-1"
        assert "Upgrade libssl3 to 3.0.11-1" in high.remediation

        unknown = next(f for f in result.findings if f.attributes["vulnerability_id"] == "CVE-2022-9999")
        assert unknown.severity is Severity.INFORMATIONAL  # UNKNOWN → informational
        assert unknown.title == "CVE-2022-9999 in zlib"  # falls back when Title empty
        assert unknown.remediation == "No fixed version available"

    def test_empty_or_garbage(self):
        assert trivy_json_to_scan_result("", image_ref="x").findings == ()
        assert trivy_json_to_scan_result("not json", image_ref="x").findings == ()
        assert trivy_json_to_scan_result({"Results": None}, image_ref="x").findings == ()


# ── TrivyScanner drives the backend + parses ───────────────────────────
class _FakeBackend:
    def __init__(self, stdout):
        self.stdout = stdout
        self.spec: ScanJobSpec | None = None

    def run(self, spec, *, on_progress=None):
        self.spec = spec
        return ScanJobResult(stdout=self.stdout, exit_code=0)


class TestTrivyScanner:
    def test_builds_fixed_argv_and_parses(self):
        backend = _FakeBackend(json.dumps(_TRIVY_JSON))
        scanner = TrivyScanner(backend=backend)
        result = scanner.scan(ScanTarget(identifier="nginx:latest"))

        # parsed
        assert len(result.findings) == 2
        # fixed argv: trivy image ... with the ref AFTER `--`
        args = backend.spec.args
        assert args[0] == "trivy" and "image" in args
        assert args[-2] == "--" and args[-1] == "nginx:latest"
        assert "--format" in args and "json" in args

    def test_rejects_malicious_ref_before_running(self):
        backend = _FakeBackend("{}")
        with pytest.raises(InvalidImageReferenceError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="-oevil"))
        assert backend.spec is None  # never reached the backend

    def test_passes_aws_creds_as_secret_env_not_argv(self):
        backend = _FakeBackend("{}")
        creds = {"AccessKeyId": "AK", "SecretAccessKey": "s", "SessionToken": "t"}
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest", credentials=creds))
        assert backend.spec.secret_env["AWS_ACCESS_KEY_ID"] == "AK"
        assert "AK" not in " ".join(backend.spec.args)  # creds never in argv
