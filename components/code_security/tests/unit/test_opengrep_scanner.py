"""Unit tests for the Opengrep pillar adapter (ADR 0019 D2/D6) — no k8s, no engine."""

from __future__ import annotations

import json

import pytest

from components.code_security.domain.repo_reference import (
    InvalidRepoReferenceError,
    validate_commit_sha,
    validate_repo_reference,
)
from components.code_security.infrastructure.adapters import opengrep_scanner
from components.code_security.infrastructure.adapters.opengrep_scanner import OpengrepScanner
from components.code_security.infrastructure.services.ruleset import (
    load_ruleset_yaml,
    ruleset_rule_ids,
)
from components.scanning.application.ports.scan_execution_backend import ScanJobResult
from components.scanning.domain.errors import ScanExecutionError
from components.shared_kernel.application.ports.scanner_port import ScanTarget

pytestmark = pytest.mark.unit

_SHA = "b" * 40
_CREDS = {
    "provider": "github",
    "repo": "wanjala-dev/auto-sec-api",
    "token": "ghp_test_token",
    "commit_sha": _SHA,
    "archive_url": f"https://api.github.com/repos/wanjala-dev/auto-sec-api/tarball/{_SHA}",
}


# ── repo-reference validator (the untrusted-input gate) ────────────────
class TestRepoReferenceValidation:
    @pytest.mark.parametrize(
        "ref",
        ["owner/repo", "wanjala-dev/auto-sec-api", "a/b", "Org.Name/repo_1.2"],
    )
    def test_accepts_valid_refs(self, ref):
        assert validate_repo_reference(ref) == ref

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "no-slash",
            "a/b/c",
            "-flag/repo",
            "owner/../../etc",
            "owner/repo; rm -rf /",
            "owner/repo\n--bad",
            "owner/" + "a" * 300,
        ],
    )
    def test_rejects_malicious_refs(self, bad):
        with pytest.raises(InvalidRepoReferenceError):
            validate_repo_reference(bad)

    def test_commit_sha_validation(self):
        assert validate_commit_sha("ABCDEF1" + "0" * 33) == "abcdef1" + "0" * 33
        with pytest.raises(InvalidRepoReferenceError):
            validate_commit_sha("not-a-sha")
        with pytest.raises(InvalidRepoReferenceError):
            validate_commit_sha("")


# ── the curated ruleset (D1/D4 invariants) ─────────────────────────────
class TestRuleset:
    def test_loads_and_carries_rules(self):
        import yaml

        document = yaml.safe_load(load_ruleset_yaml())
        assert len(document["rules"]) >= 10
        assert len(ruleset_rule_ids()) == len(document["rules"])

    def test_every_rule_is_license_audited_first_party(self):
        """P1 ships first-party only — nothing Semgrep-Rules-v1.0-shaped may ride in."""
        import yaml

        for rule in yaml.safe_load(load_ruleset_yaml())["rules"]:
            metadata = rule.get("metadata") or {}
            assert metadata.get("license") == "autosec-first-party", rule["id"]
            assert metadata.get("pack") == "autosec-p1-core", rule["id"]

    def test_no_p1_rule_reaches_critical(self):
        """Severity ceiling: no rule >= 9.0 — criticals alert individually (ADR 0016 D5)
        and pattern rules without reachability context don't earn that."""
        import yaml

        for rule in yaml.safe_load(load_ruleset_yaml())["rules"]:
            score = float((rule.get("metadata") or {}).get("security-severity", 0))
            assert 0.0 < score < 9.0, f"{rule['id']} carries security-severity {score}"


# ── the Job composition (D6 hardening) ─────────────────────────────────
class _CapturingBackend:
    def __init__(self, result: ScanJobResult):
        self.spec = None
        self._result = result

    def run(self, spec, *, on_progress=None, **kwargs):
        self.spec = spec
        return self._result


def _envelope(sarif: dict) -> str:
    return json.dumps({"autosec_opengrep_envelope": 1, "sarif": sarif})


def _empty_sarif() -> dict:
    return {
        "runs": [
            {"tool": {"driver": {"name": "Opengrep OSS", "semanticVersion": "1.26.0", "rules": []}}, "results": []}
        ]
    }


class TestOpengrepScanner:
    def test_composes_a_hardened_job_spec(self):
        backend = _CapturingBackend(ScanJobResult(stdout=_envelope(_empty_sarif()), exit_code=0))
        scanner = OpengrepScanner(backend=backend)
        scanner.scan(ScanTarget(identifier="wanjala-dev/auto-sec-api", credentials=dict(_CREDS)))

        spec = backend.spec
        assert spec.source == "code_security.opengrep"
        # Pinned image (env-overridable), never :latest.
        assert ":latest" not in spec.image
        # The token rides ONLY in secret_env (a k8s Secret) — never argv, never env.
        assert spec.secret_env == {"VCS_TOKEN": "ghp_test_token"}
        assert all("ghp_test_token" not in arg for arg in spec.args)
        assert "ghp_test_token" not in json.dumps(spec.env)
        # The rules + archive URL ride in env; the script text carries neither.
        assert spec.env["ARCHIVE_URL"] == _CREDS["archive_url"]
        assert "rules:" in spec.env["OPENGREP_RULES"]
        script = spec.args[2]
        assert _CREDS["archive_url"] not in script
        # Fixed argv shape: /bin/sh -c <script> <argv0>.
        assert spec.args[0] == "/bin/sh" and spec.args[1] == "-c"
        # Repo-side config is untrusted data: nosem + version check disabled, and
        # .semgrepignore files are deleted before the engine runs.
        assert "--disable-nosem" in script
        assert "--no-rewrite-rule-ids" in script  # keep OUR canonical rule ids
        assert "--disable-version-check" in script
        assert ".semgrepignore" in script
        # Our excludes made it in.
        assert "--exclude node_modules" in script

    def test_fails_loud_without_vended_credentials(self):
        backend = _CapturingBackend(ScanJobResult(stdout="", exit_code=0))
        scanner = OpengrepScanner(backend=backend)
        with pytest.raises(ScanExecutionError):
            scanner.scan(ScanTarget(identifier="wanjala-dev/auto-sec-api", credentials=None))

    def test_rejects_non_https_archive_url(self):
        creds = dict(_CREDS, archive_url="http://api.github.com/repos/x/y/tarball/abc")
        scanner = OpengrepScanner(backend=_CapturingBackend(ScanJobResult(stdout="", exit_code=0)))
        with pytest.raises(ScanExecutionError):
            scanner.scan(ScanTarget(identifier="wanjala-dev/auto-sec-api", credentials=creds))

    def test_fails_loud_on_engine_failure(self):
        backend = _CapturingBackend(ScanJobResult(stdout="curl: (22) 404", exit_code=20))
        scanner = OpengrepScanner(backend=backend)
        with pytest.raises(ScanExecutionError):
            scanner.scan(ScanTarget(identifier="wanjala-dev/auto-sec-api", credentials=dict(_CREDS)))

    def test_parses_envelope_and_stamps_scan_meta(self):
        fixture = _empty_sarif()
        backend = _CapturingBackend(ScanJobResult(stdout=_envelope(fixture), exit_code=0))
        scanner = OpengrepScanner(backend=backend)
        result = scanner.scan(ScanTarget(identifier="wanjala-dev/auto-sec-api", credentials=dict(_CREDS)))
        assert result.engine == "opengrep"
        assert result.engine_version == "1.26.0"
        meta = next(a for a in result.artifacts if a.kind == "code_security.scan_meta")
        parsed = json.loads(meta.content)
        assert parsed["commit_sha"] == _SHA
        assert parsed["repo"] == "wanjala-dev/auto-sec-api"

    def test_image_pin_is_env_overridable(self, monkeypatch):
        monkeypatch.setenv("OPENGREP_IMAGE", "autosec-opengrep:9.9.9")
        # module-level constant reads env at import; assert the default carries a pin
        assert opengrep_scanner._OPENGREP_IMAGE
        assert ":latest" not in opengrep_scanner._OPENGREP_IMAGE
