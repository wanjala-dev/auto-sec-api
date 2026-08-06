"""Unit tests for the Trivy pillar (ADR 0006) — pure logic, no k8s, no trivy binary."""

from __future__ import annotations

import json

import pytest

from components.container_security.domain.image_reference import (
    InvalidImageReferenceError,
    validate_image_reference,
)
from components.container_security.infrastructure.adapters import trivy_scanner
from components.container_security.infrastructure.adapters.trivy_scanner import TrivyScanner
from components.container_security.infrastructure.services.trivy_normalizer import (
    trivy_json_to_scan_result,
)
from components.scanning.application.ports.scan_execution_backend import (
    ScanJobResult,
    ScanJobSpec,
)
from components.scanning.domain.errors import ScanExecutionError
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

    def test_captures_numeric_cvss_base_prefer_nvd_v3(self):
        """ADR 0013 P2 (decision #5): the numeric CVSS base must be captured for the scorer."""
        data = {
            "Results": [
                {
                    "Target": "app",
                    "Class": "lang-pkgs",
                    "Type": "npm",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2021-44228",
                            "PkgName": "log4j",
                            "InstalledVersion": "2.14.0",
                            "Severity": "CRITICAL",
                            "CVSS": {
                                "redhat": {"V3Score": 7.5},
                                "nvd": {"V2Score": 9.3, "V3Score": 10.0},
                            },
                        }
                    ],
                }
            ]
        }
        result = trivy_json_to_scan_result(data, image_ref="app:1")
        (finding,) = result.findings
        assert finding.attributes["cvss_base"] == 10.0  # NVD V3 preferred over redhat/V2

    def test_no_cvss_map_omits_cvss_base(self):
        data = {
            "Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-2020-1", "PkgName": "x", "Severity": "HIGH"}]}]
        }
        (finding,) = trivy_json_to_scan_result(data, image_ref="app:1").findings
        assert "cvss_base" not in finding.attributes


# ── TrivyScanner drives the backend + parses ───────────────────────────
def _envelope(vuln, sbom="__omit__"):
    """The in-Job script's stdout contract: one JSON envelope carrying both outputs."""
    doc = {"autosec_trivy_envelope": 1, "vuln": vuln}
    if sbom != "__omit__":
        doc["sbom"] = sbom
    return json.dumps(doc)


_SBOM_JSON = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.6",
    "components": [
        {"name": "libssl3", "version": "3.0.9-1", "type": "library"},
        {"name": "zlib", "version": "1.2.13", "type": "library"},
    ],
}


class _FakeBackend:
    def __init__(self, stdout, *, exit_code=0, timed_out=False):
        self.stdout = stdout
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.spec: ScanJobSpec | None = None

    def run(self, spec, *, on_progress=None):
        self.spec = spec
        return ScanJobResult(stdout=self.stdout, exit_code=self.exit_code, timed_out=self.timed_out)


class TestTrivyScanner:
    def test_builds_fixed_script_argv_and_parses(self):
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        scanner = TrivyScanner(backend=backend)
        result = scanner.scan(ScanTarget(identifier="nginx:latest"))

        # parsed
        assert len(result.findings) == 2
        # fixed argv: sh -c <script> <argv0> <ref> — the UNTRUSTED ref rides ONLY as
        # the positional "$1", never interpolated into the script text.
        args = backend.spec.args
        assert args[0] == "/bin/sh" and args[1] == "-c"
        script = args[2]
        assert args[-1] == "nginx:latest"
        assert "nginx:latest" not in script
        assert '-- "$1"' in script
        # pass 1 (vuln) is unchanged in spirit: json format, vuln scanners
        assert "--format json" in script and "--scanners vuln" in script

    def test_script_runs_a_cyclonedx_sbom_pass(self):
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        script = backend.spec.args[2]
        assert "--format cyclonedx" in script
        # the envelope keys the worker parses
        assert "autosec_trivy_envelope" in script
        # SBOM failure tolerance is IN the script: sbom_ok gating, null fallback
        assert '"sbom":null' in script

    def test_rejects_malicious_ref_before_running(self):
        backend = _FakeBackend("{}")
        with pytest.raises(InvalidImageReferenceError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="-oevil"))
        assert backend.spec is None  # never reached the backend

    def test_passes_aws_creds_as_secret_env_not_argv(self):
        backend = _FakeBackend(_envelope({}, None))
        creds = {"AccessKeyId": "AK", "SecretAccessKey": "s", "SessionToken": "t"}
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest", credentials=creds))
        assert backend.spec.secret_env["AWS_ACCESS_KEY_ID"] == "AK"
        assert "AK" not in " ".join(backend.spec.args)  # creds never in argv

    def test_wires_a_writable_cache_dir_for_readonly_rootfs(self):
        # The hardened Job runs read-only-rootfs; Trivy MUST cache under the writable /tmp
        # mount, else it FATAL-errors ("mkdir /.cache: read-only file system") on lang-DB
        # download. The script reads "$TRIVY_CACHE_DIR", which the spec env provides.
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        script = backend.spec.args[2]
        assert '--cache-dir "$TRIVY_CACHE_DIR"' in script
        assert backend.spec.env.get("TRIVY_CACHE_DIR", "").startswith("/tmp/")
        assert backend.spec.env.get("HOME") == "/tmp"


class TestTrivySbomEnvelope:
    """The SBOM leg of the envelope: present → artifact; absent → honest no-artifact."""

    def test_sbom_present_becomes_a_scan_artifact(self):
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        result = TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert len(result.findings) == 2  # vuln pipeline untouched
        (artifact,) = result.artifacts
        assert artifact.kind == trivy_scanner.SBOM_ARTIFACT_KIND
        assert artifact.media_type == trivy_scanner.SBOM_MEDIA_TYPE
        parsed = json.loads(artifact.content)
        assert parsed["specVersion"] == "1.6"
        assert len(parsed["components"]) == 2

    def test_sbom_null_yields_no_artifact_but_scan_succeeds(self, caplog):
        # THE POLICY: a failed SBOM pass never fails the vuln scan — sbom stays an
        # honest absent state (warned, not raised).
        import logging

        backend = _FakeBackend(_envelope(_TRIVY_JSON, None))
        with caplog.at_level(logging.WARNING, logger=trivy_scanner.__name__):
            result = TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert len(result.findings) == 2
        assert result.artifacts == ()
        assert any("trivy_sbom_absent" in r.message for r in caplog.records)

    def test_legacy_plain_trivy_json_still_parses(self):
        # Backward compatibility: pre-envelope output (plain Trivy JSON) is treated
        # as the vuln report with no SBOM.
        backend = _FakeBackend(json.dumps(_TRIVY_JSON))
        result = TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert len(result.findings) == 2
        assert result.artifacts == ()

    def test_unsafe_server_url_fails_loud(self, monkeypatch):
        # The server URL is trusted config, but a typo'd/hostile value must fail loud
        # rather than be interpolated into the script.
        monkeypatch.setenv("TRIVY_SERVER_URL", "http://x; rm -rf /")
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        with pytest.raises(ScanExecutionError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert backend.spec is None

    def test_server_url_lands_in_the_vuln_pass(self, monkeypatch):
        monkeypatch.setenv("TRIVY_SERVER_URL", "http://trivy-server:4954")
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert "--server http://trivy-server:4954" in backend.spec.args[2]

    def test_nonzero_exit_raises_instead_of_recording_empty_result(self):
        # THE regression this fix exists for: a crashed scan (non-zero exit, stdout = an
        # error message, not JSON) must FAIL LOUD, not parse to 0 findings and look clean.
        backend = _FakeBackend("FATAL Fatal error: Unable to initialize the Java DB", exit_code=1)
        with pytest.raises(ScanExecutionError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))

    def test_timeout_raises(self):
        backend = _FakeBackend("", exit_code=124, timed_out=True)
        with pytest.raises(ScanExecutionError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))


# ── the fat-image timeout fix — explicit --timeout + backend deadline ──
class TestTrivyScanTimeout:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv("TRIVY_SCAN_TIMEOUT", raising=False)

    def _scan(self):
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        return backend.spec

    def test_script_carries_explicit_timeout_default_15m(self):
        # Trivy's implicit 5m default dies on fat images (node:18-bullseye) with
        # "context deadline exceeded"; every trivy invocation in the script must carry
        # an explicit --timeout.
        spec = self._scan()
        script = spec.args[2]
        assert script.count("--timeout 15m") == 2  # the vuln pass AND the SBOM pass

    def test_timeout_env_overridable(self, monkeypatch):
        monkeypatch.setenv("TRIVY_SCAN_TIMEOUT", "45m")
        spec = self._scan()
        assert "--timeout 45m" in spec.args[2]
        assert spec.timeout_seconds == 45 * 60 + trivy_scanner._BACKEND_TIMEOUT_HEADROOM_SECONDS

    def test_backend_deadline_strictly_outlives_trivy_timeout(self):
        # INVARIANT: Job activeDeadlineSeconds / subprocess timeout = trivy --timeout +
        # headroom, so a slow scan is ended by Trivy's own fail-loud exit — never by the
        # Job deadline killing the pod mid-scan.
        spec = self._scan()
        trivy_seconds = trivy_scanner._duration_seconds("15m")
        assert spec.timeout_seconds == trivy_seconds + trivy_scanner._BACKEND_TIMEOUT_HEADROOM_SECONDS
        assert spec.timeout_seconds > trivy_seconds

    def test_garbage_timeout_env_fails_loud_before_running(self, monkeypatch):
        monkeypatch.setenv("TRIVY_SCAN_TIMEOUT", "soon-ish")
        backend = _FakeBackend(_envelope(_TRIVY_JSON, _SBOM_JSON))
        with pytest.raises(ScanExecutionError):
            TrivyScanner(backend=backend).scan(ScanTarget(identifier="nginx:latest"))
        assert backend.spec is None  # never reached the backend

    @pytest.mark.parametrize(
        ("value", "seconds"),
        [("15m", 900), ("1h", 3600), ("900s", 900), ("1h30m", 5400), ("2h5m10s", 7510)],
    )
    def test_duration_parser(self, value, seconds):
        assert trivy_scanner._duration_seconds(value) == seconds

    @pytest.mark.parametrize("bad", ["", "  ", "15", "m15", "15 m", "-5m", "1.5h"])
    def test_duration_parser_rejects_garbage(self, bad):
        with pytest.raises(ScanExecutionError):
            trivy_scanner._duration_seconds(bad)
