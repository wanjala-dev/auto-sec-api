"""The silent-false-negative guard, tested across all three engines.

The bug this locks down: an engine that exits **0** while its output is truncated,
empty, or corrupt used to be parsed "defensively" into zero findings, so the spine
recorded a COMPLETED ScanRun over a mutilated scan — a customer's account reported
clean because the result was cut off. These tests assert the inverse invariant:

    unusable output ⇒ ``IncompleteScanOutputError`` ⇒ FAILED run
    genuinely clean output ⇒ parses ⇒ COMPLETED run with zero findings

Both halves matter. A guard that only failed loud would be just as wrong if it also
failed an honestly-clean scan — "no findings" is a real, reportable answer.
"""

from __future__ import annotations

import json

import pytest

from components.scanning.domain.engine_output import parse_engine_result_document
from components.scanning.domain.errors import IncompleteScanOutputError, ScanExecutionError

pytestmark = pytest.mark.unit


def _truncated(document: str, *, at: float = 0.6) -> str:
    """Cut a document short the way pod-log rotation does — mid-record, no closer."""
    return document[: int(len(document) * at)]


# A realistic Prowler OCSF array and Trivy/Opengrep envelopes, big enough that slicing
# them lands mid-record (exactly the truncation fingerprint we must catch).
_OCSF_RECORDS = [
    {"finding_info": {"uid": f"check-{i}"}, "status_code": "FAIL", "severity": "High", "pad": "x" * 200}
    for i in range(50)
]
_OCSF_DOCUMENT = json.dumps(_OCSF_RECORDS)
_TRIVY_DOCUMENT = json.dumps(
    {"autosec_trivy_envelope": 1, "vuln": {"Results": [{"Target": "img", "Vulnerabilities": []}]}, "sbom": None}
)
_OPENGREP_DOCUMENT = json.dumps({"autosec_opengrep_envelope": 1, "sarif": {"runs": [{"results": []}]}})


class TestParseEngineResultDocument:
    """The shared guard — the one place document integrity is decided."""

    @pytest.mark.parametrize("stdout", ["", "   ", "\n\n", None])
    def test_empty_output_fails_loud(self, stdout):
        # Every engine always emits its document; a clean Prowler scan still prints "[]".
        # So empty means "we got nothing", never "the target was clean".
        with pytest.raises(IncompleteScanOutputError) as exc:
            parse_engine_result_document(stdout, engine="prowler")
        assert "no output" in str(exc.value)

    @pytest.mark.parametrize(
        ("document", "engine"),
        [(_OCSF_DOCUMENT, "prowler"), (_TRIVY_DOCUMENT, "trivy"), (_OPENGREP_DOCUMENT, "opengrep")],
    )
    def test_truncated_output_fails_loud_and_is_named_as_truncation(self, document, engine):
        with pytest.raises(IncompleteScanOutputError) as exc:
            parse_engine_result_document(_truncated(document), engine=engine)
        message = str(exc.value)
        # The operator must see WHY, not just THAT — "TRUNCATED" is the actionable word.
        assert "TRUNCATED" in message
        assert engine in message

    def test_truncation_error_reports_the_size(self):
        # ~10 MiB of well-formed JSON cut short: the pod-log-rotation scenario at real scale.
        oversized = json.dumps([{"uid": i, "pad": "x" * 512} for i in range(20_000)])
        assert len(oversized) > 10 * 1024 * 1024
        with pytest.raises(IncompleteScanOutputError) as exc:
            parse_engine_result_document(_truncated(oversized), engine="prowler")
        assert "MiB" in str(exc.value)

    def test_corrupt_non_truncated_output_fails_loud(self):
        with pytest.raises(IncompleteScanOutputError):
            parse_engine_result_document("FATAL: could not assume role", engine="prowler")

    @pytest.mark.parametrize("scalar", ["null", "123", '"a string"', "true"])
    def test_bare_scalar_is_not_a_result_document(self, scalar):
        with pytest.raises(IncompleteScanOutputError):
            parse_engine_result_document(scalar, engine="trivy")

    @pytest.mark.parametrize("document", [_OCSF_DOCUMENT, _TRIVY_DOCUMENT, _OPENGREP_DOCUMENT, "[]", "{}"])
    def test_complete_documents_parse(self, document):
        # Including the genuinely-clean shapes: "[]" (Prowler, no findings) and "{}".
        assert parse_engine_result_document(document, engine="any") == json.loads(document)

    def test_error_is_a_scan_execution_error_so_the_spine_fails_the_run(self):
        # run_scan_and_ingest catches Exception → FAILED ScanRun + audit_scan_failed, and the
        # adapters' existing fail-loud contract is ScanExecutionError. Subclassing keeps ONE
        # failure path rather than adding a second one to every caller.
        assert issubclass(IncompleteScanOutputError, ScanExecutionError)

    def test_snippets_are_bounded_so_a_scan_never_floods_logs_or_the_error_column(self):
        # ScanRun.error is truncated to 255 chars; the message must be diagnostic, not a dump.
        huge = "[" + "x" * 5_000_000
        with pytest.raises(IncompleteScanOutputError) as exc:
            parse_engine_result_document(huge, engine="prowler")
        assert len(str(exc.value)) < 1000


class TestProwlerAdapterOutputGuard:
    def test_truncated_ocsf_fails_loud(self):
        from components.cloud_posture.infrastructure.adapters.prowler_scanner import _parse_ocsf_stdout

        with pytest.raises(IncompleteScanOutputError):
            _parse_ocsf_stdout(_truncated(_OCSF_DOCUMENT))

    def test_empty_ocsf_fails_loud(self):
        from components.cloud_posture.infrastructure.adapters.prowler_scanner import _parse_ocsf_stdout

        with pytest.raises(IncompleteScanOutputError):
            _parse_ocsf_stdout("")

    def test_genuinely_clean_account_still_parses(self):
        from components.cloud_posture.infrastructure.adapters.prowler_scanner import _parse_ocsf_stdout

        # An account with zero failing checks: a real answer, must NOT fail.
        assert _parse_ocsf_stdout("[]") == []

    def test_complete_ocsf_parses_every_record(self):
        from components.cloud_posture.infrastructure.adapters.prowler_scanner import _parse_ocsf_stdout

        assert len(_parse_ocsf_stdout(_OCSF_DOCUMENT)) == 50


class TestTrivyAdapterOutputGuard:
    def test_truncated_envelope_fails_loud(self):
        from components.container_security.infrastructure.adapters.trivy_scanner import _split_envelope

        with pytest.raises(IncompleteScanOutputError):
            _split_envelope(_truncated(_TRIVY_DOCUMENT), image_ref="alpine:3.19")

    def test_engine_error_transcript_fails_loud(self):
        from components.container_security.infrastructure.adapters.trivy_scanner import _split_envelope

        with pytest.raises(IncompleteScanOutputError):
            _split_envelope("FATAL\tunable to initialize scanner", image_ref="alpine:3.19")

    def test_clean_image_envelope_completes_normally(self):
        from components.container_security.infrastructure.adapters.trivy_scanner import _split_envelope

        vuln, sbom = _split_envelope(_TRIVY_DOCUMENT, image_ref="alpine:3.19")
        assert vuln["Results"][0]["Vulnerabilities"] == []
        assert sbom is None  # honest absent state, unchanged policy

    def test_legacy_plain_trivy_json_is_still_tolerated(self):
        from components.container_security.infrastructure.adapters.trivy_scanner import _split_envelope

        legacy = json.dumps({"Results": [{"Target": "img", "Vulnerabilities": []}]})
        vuln, sbom = _split_envelope(legacy, image_ref="alpine:3.19")
        assert vuln["Results"][0]["Target"] == "img"
        assert sbom is None


class TestOpengrepAdapterOutputGuard:
    def test_truncated_sarif_envelope_fails_loud(self):
        from components.code_security.infrastructure.adapters.opengrep_scanner import _unwrap_envelope

        with pytest.raises(IncompleteScanOutputError):
            _unwrap_envelope(_truncated(_OPENGREP_DOCUMENT), repo="acme/api")

    def test_envelope_without_sarif_fails_loud(self):
        from components.code_security.infrastructure.adapters.opengrep_scanner import _unwrap_envelope

        with pytest.raises(IncompleteScanOutputError):
            _unwrap_envelope(json.dumps({"autosec_opengrep_envelope": 1, "sarif": None}), repo="acme/api")

    def test_clean_repo_sarif_completes_normally(self):
        from components.code_security.infrastructure.adapters.opengrep_scanner import _unwrap_envelope

        sarif = _unwrap_envelope(_OPENGREP_DOCUMENT, repo="acme/api")
        assert sarif["runs"][0]["results"] == []

    def test_bare_sarif_is_still_tolerated(self):
        from components.code_security.infrastructure.adapters.opengrep_scanner import _unwrap_envelope

        bare = json.dumps({"runs": [{"results": []}]})
        assert _unwrap_envelope(bare, repo="acme/api")["runs"][0]["results"] == []
