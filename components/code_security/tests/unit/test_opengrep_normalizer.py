"""Unit tests for the Opengrep SARIF normalizer (ADR 0019 D2/D4/D8) — pure logic.

The primary fixture is REAL recorded output: opengrep v1.26.0 run over the rule
pack's positive+negative corpus (``tests/fixtures/opengrep_corpus.sarif.json``),
so the parser is grounded in the engine's actual SARIF dialect, not a guess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.code_security.infrastructure.services.opengrep_normalizer import (
    opengrep_sarif_to_scan_result,
)
from components.shared_kernel.domain.security import Severity

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "opengrep_corpus.sarif.json"
_REPO = "wanjala-dev/auto-sec-api"
_SHA = "a" * 40


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text())


class TestRecordedSarif:
    def test_maps_every_result(self):
        result = opengrep_sarif_to_scan_result(_load_fixture(), repo=_REPO, commit_sha=_SHA)
        assert result.engine == "opengrep"
        assert result.engine_version == "1.26.0"
        assert len(result.findings) == 20
        assert result.failed_count == 20 and result.total_checks == 20

    def test_finding_carries_the_code_location(self):
        result = opengrep_sarif_to_scan_result(_load_fixture(), repo=_REPO, commit_sha=_SHA)
        jwt = next(f for f in result.findings if f.attributes["rule_id"] == "autosec.python.jwt-verify-disabled")
        assert jwt.source == "code_security.opengrep"
        assert jwt.asset_urn == f"urn:vcs:github:{_REPO}"
        assert jwt.attributes["repo"] == _REPO
        assert jwt.attributes["commit_sha"] == _SHA
        assert jwt.attributes["path"] == "corpus/vuln.py"
        assert jwt.attributes["start_line"] > 0
        assert "jwt.decode" in jwt.attributes["snippet"]
        assert jwt.attributes["cwe"] == ["CWE-347"]
        assert jwt.attributes["language"] == "python"
        assert jwt.attributes["confidence"] == "high"

    def test_severity_from_security_severity_score(self):
        result = opengrep_sarif_to_scan_result(_load_fixture(), repo=_REPO, commit_sha=_SHA)
        by_rule = {}
        for finding in result.findings:
            by_rule.setdefault(finding.attributes["rule_id"], finding)
        # 8.9 → HIGH (the P1 pack's ceiling — criticals need >= 9.0)
        assert by_rule["autosec.python.jwt-verify-disabled"].severity is Severity.HIGH
        # 6.5 → MEDIUM
        assert by_rule["autosec.python.pickle-load-untrusted"].severity is Severity.MEDIUM
        # 4.7 → MEDIUM
        assert by_rule["autosec.python.tempfile-mktemp"].severity is Severity.MEDIUM

    def test_cvss_base_feeds_contextual_risk(self):
        result = opengrep_sarif_to_scan_result(_load_fixture(), repo=_REPO, commit_sha=_SHA)
        jwt = next(f for f in result.findings if f.attributes["rule_id"] == "autosec.python.jwt-verify-disabled")
        assert jwt.attributes["cvss_base"] == 8.9

    def test_no_p1_finding_is_critical(self):
        """The P1 pack severity ceiling (ADR 0016 D5: criticals alert individually)."""
        result = opengrep_sarif_to_scan_result(_load_fixture(), repo=_REPO, commit_sha=_SHA)
        assert all(f.severity is not Severity.CRITICAL for f in result.findings)


class TestFingerprintIdentity:
    def _result_doc(self, *, start_line: int, match_id: str | None, snippet: str = "eval(x)") -> dict:
        result = {
            "ruleId": "autosec.python.eval-exec-dynamic",
            "message": {"text": "eval"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": "app/main.py"},
                        "region": {"startLine": start_line, "endLine": start_line, "snippet": {"text": snippet}},
                    }
                }
            ],
        }
        if match_id is not None:
            result["fingerprints"] = {"matchBasedId/v1": match_id}
        return {"runs": [{"tool": {"driver": {"name": "Opengrep OSS", "rules": []}}, "results": [result]}]}

    def test_line_numbers_never_enter_the_fingerprint(self):
        """An edit above the finding (line shift, same engine match id) must not mint
        a new finding — the D4 invariant."""
        before = opengrep_sarif_to_scan_result(
            self._result_doc(start_line=10, match_id="abc_0"), repo=_REPO, commit_sha=_SHA
        )
        after = opengrep_sarif_to_scan_result(
            self._result_doc(start_line=99, match_id="abc_0"), repo=_REPO, commit_sha=_SHA
        )
        assert before.findings[0].fingerprint == after.findings[0].fingerprint
        assert "10" not in before.findings[0].fingerprint.split("|")[-1]

    def test_fingerprint_carries_repo_rule_and_path(self):
        result = opengrep_sarif_to_scan_result(
            self._result_doc(start_line=10, match_id="abc_0"), repo=_REPO, commit_sha=_SHA
        )
        fp = result.findings[0].fingerprint
        assert fp.startswith(f"{_REPO}|autosec.python.eval-exec-dynamic|app/main.py|")
        assert fp.endswith("_0")  # the occurrence suffix keeps identical matches distinct

    def test_two_identical_matches_in_one_file_stay_distinct(self):
        a = opengrep_sarif_to_scan_result(
            self._result_doc(start_line=10, match_id="abc_0"), repo=_REPO, commit_sha=_SHA
        )
        b = opengrep_sarif_to_scan_result(
            self._result_doc(start_line=20, match_id="abc_1"), repo=_REPO, commit_sha=_SHA
        )
        assert a.findings[0].fingerprint != b.findings[0].fingerprint

    def test_fingerprint_always_fits_the_ssot_identity_column(self):
        doc = self._result_doc(start_line=10, match_id="f" * 128 + "_0")
        doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
            "very/" * 60 + "deep.py"
        )
        result = opengrep_sarif_to_scan_result(doc, repo=_REPO, commit_sha=_SHA)
        assert len(result.findings[0].fingerprint) <= 255

    def test_fallback_content_hash_when_engine_fingerprint_absent(self):
        """No engine fingerprint → snippet content hash; still line-stable."""
        a = opengrep_sarif_to_scan_result(self._result_doc(start_line=10, match_id=None), repo=_REPO, commit_sha=_SHA)
        b = opengrep_sarif_to_scan_result(self._result_doc(start_line=42, match_id=None), repo=_REPO, commit_sha=_SHA)
        assert a.findings[0].fingerprint == b.findings[0].fingerprint
        # the fallback is a content digest, marked with the "s" prefix
        assert a.findings[0].fingerprint.rsplit("|", 1)[-1].startswith("s")

    def test_snippet_capped(self):
        doc = self._result_doc(start_line=1, match_id="x_0", snippet="A" * 5000)
        result = opengrep_sarif_to_scan_result(doc, repo=_REPO, commit_sha=_SHA)
        assert len(result.findings[0].attributes["snippet"]) == 2000


class TestSecretMasking:
    def test_secret_class_rule_snippet_is_masked(self):
        """A hardcoded-credential rule's match must never replicate the secret (D8)."""
        doc = {
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Opengrep OSS",
                            "rules": [
                                {
                                    "id": "autosec.generic.hardcoded-secret",
                                    "defaultConfiguration": {"level": "error"},
                                    "properties": {"tags": ["CWE-798", "secrets"], "security-severity": "8.0"},
                                }
                            ],
                        }
                    },
                    "results": [
                        {
                            "ruleId": "autosec.generic.hardcoded-secret",
                            "message": {"text": "hardcoded secret"},
                            "fingerprints": {"matchBasedId/v1": "s_0"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "settings.py"},
                                        "region": {
                                            "startLine": 3,
                                            "endLine": 3,
                                            "snippet": {"text": 'AWS_KEY = "AKIASUPERSECRET"'},
                                        },
                                    }
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result = opengrep_sarif_to_scan_result(doc, repo=_REPO, commit_sha=_SHA)
        snippet = result.findings[0].attributes["snippet"]
        assert "AKIASUPERSECRET" not in snippet
        assert "masked" in snippet


class TestMalformedInput:
    @pytest.mark.parametrize("raw", ["", "not json", "[]", json.dumps({"runs": []})])
    def test_malformed_yields_empty_result(self, raw):
        result = opengrep_sarif_to_scan_result(raw, repo=_REPO, commit_sha=_SHA)
        assert result.findings == ()
