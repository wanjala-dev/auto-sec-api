"""ProwlerScanner + records_to_scan_result — the ScannerPort seam (ADR 0004 Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    records_to_scan_result,
)
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
    scanner = ProwlerScanner()
    assert isinstance(scanner, ScannerPort)

    target = ScanTarget(
        identifier="123456789012",
        credentials={"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"},
        params={"regions": ["us-east-1"]},
    )
    with patch(
        "components.cloud_posture.infrastructure.adapters.prowler_runner.run_prowler",
        return_value=_records(),
    ) as m_run:
        result = scanner.scan(target)

    m_run.assert_called_once()
    kwargs = m_run.call_args.kwargs
    assert kwargs["account_id"] == "123456789012"
    assert kwargs["regions"] == ["us-east-1"]
    assert kwargs["credentials"]["AccessKeyId"] == "x"
    assert len(result.findings) == 2
