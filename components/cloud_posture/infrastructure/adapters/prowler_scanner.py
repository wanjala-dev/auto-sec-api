"""Prowler CSPM scanner — the first ScannerPort adapter (ADR 0004 Phase 4).

A driven adapter: runs Prowler (the engine) with the vended credentials, then hands
its OCSF output to the pure ``records_to_scan_result`` transform (which parses +
normalizes to the shared ``NormalizedFinding`` shape). Trivy (Phase 5) is another
adapter of the same port — a new adapter, not a new pipeline.
"""

from __future__ import annotations

from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScannerPort,
    ScanResult,
    ScanTarget,
)

_ENGINE = "prowler"


class ProwlerScanner(ScannerPort):
    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        from components.cloud_posture.infrastructure.adapters.prowler_runner import run_prowler
        from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
            records_to_scan_result,
        )

        records = run_prowler(
            credentials=target.credentials or {},
            account_id=target.identifier,
            regions=list(target.params.get("regions") or []),
            progress_callback=on_progress,
        )
        return records_to_scan_result(records, engine_version=_ENGINE)
