"""ProwlerScanner + records_to_scan_result — the ScannerPort seam (ADR 0004 Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    records_to_scan_result,
)
from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend
from components.shared_kernel.application.ports.scanner_port import ScannerPort, ScanResult, ScanTarget
from components.shared_kernel.domain.security import NormalizedFinding, Severity

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_ocsf_sample.json"


def _records():
    return json.loads(_FIXTURE.read_text())


@pytest.mark.unit
def test_records_to_scan_result_normalizes_and_counts():
    result = records_to_scan_result(_records(), engine_version="prowler-5.x")

    assert isinstance(result, ScanResult)
    assert result.engine == "prowler"
    assert result.engine_version == "prowler-5.x"
    # Fixture: 3 checks (2 actionable FAIL + 1 PASS).
    assert result.total_checks == 3
    assert result.passed_count == 1
    assert result.failed_count == 2
    assert len(result.findings) == 2  # only actionable

    assert all(isinstance(f, NormalizedFinding) for f in result.findings)
    by_check = {f.attributes["check_id"]: f for f in result.findings}
    root = by_check["iam_root_mfa_enabled"]
    assert root.source == "cloud_posture.prowler"
    assert root.severity is Severity.CRITICAL
    assert root.asset_urn == "arn:aws:iam::123456789012:root"
    assert root.fingerprint == "iam_root_mfa_enabled|123456789012|arn:aws:iam::123456789012:root"


@pytest.mark.unit
def test_prowler_scanner_is_a_scanner_port_and_runs_the_engine():
    backend = RecordsBackend(_records())
    scanner = ProwlerScanner(backend=backend)
    assert isinstance(scanner, ScannerPort)

    target = ScanTarget(
        identifier="123456789012",
        credentials={"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"},
        params={"regions": ["us-east-1"]},
    )
    result = scanner.scan(target)

    # The engine ran on the backend exactly once: the official prowler CLI with native json-ocsf
    # and the validated region, creds mounted as secret_env (never in the command).
    assert len(backend.calls) == 1
    spec = backend.calls[0]
    assert spec.source == "cloud_posture.prowler"
    script = spec.args[-1]  # ("sh", "-c", <script>)
    assert "prowler aws" in script
    assert "--output-formats json-ocsf" in script
    assert "--region us-east-1" in script
    # The account id is a label only — it must never enter the command line.
    assert "123456789012" not in script
    assert spec.secret_env["AWS_ACCESS_KEY_ID"] == "x"
    assert spec.run_as_user == 1000  # the official prowler image's non-root uid
    # A full account scan loads every provider SDK + accumulates findings in-memory; the backend's
    # 2Gi default OOMKills it (→ 0 findings, silent). Prowler must ask for headroom.
    assert spec.memory_limit == "4Gi"
    assert len(result.findings) == 2


@pytest.mark.unit
def test_prowler_scanner_rejects_a_malicious_region():
    from components.cloud_posture.domain.aws_scan_target import InvalidAwsScanTargetError

    scanner = ProwlerScanner(backend=RecordsBackend([]))
    target = ScanTarget(
        identifier="123456789012",
        credentials={},
        params={"regions": ["us-east-1; rm -rf /"]},  # injection attempt
    )
    with pytest.raises(InvalidAwsScanTargetError):
        scanner.scan(target)


def _scan_target():
    return ScanTarget(
        identifier="123456789012",
        credentials={"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"},
        params={"regions": ["us-east-1"]},
    )


@pytest.mark.unit
def test_nonzero_exit_raises_instead_of_recording_empty_result():
    # THE regression this fix exists for: a crashed Prowler Job (FATAL-error / OOMKill, whose
    # `cat` of a missing OCSF file exits non-zero) must FAIL LOUD, not parse to 0 findings and
    # be recorded as a COMPLETED clean scan with the account link promoted to VERIFIED.
    from components.scanning.domain.errors import ScanExecutionError

    backend = RecordsBackend([], exit_code=1)  # non-zero exit → engine failure
    with pytest.raises(ScanExecutionError):
        ProwlerScanner(backend=backend).scan(_scan_target())


@pytest.mark.unit
def test_timeout_raises():
    # A Prowler Job that exceeds its deadline must surface as a failed run, never "0 findings".
    from components.scanning.domain.errors import ScanExecutionError

    backend = RecordsBackend([], exit_code=124, timed_out=True)
    with pytest.raises(ScanExecutionError):
        ProwlerScanner(backend=backend).scan(_scan_target())
