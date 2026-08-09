"""Golden master: the spine migration must not move a single AWS byte.

Finding identity is ``(workspace, source, fingerprint)`` and dedup continuity is
customer-facing — a fingerprint or URN change re-opens every existing finding
as a duplicate. The golden fixture
(``fixtures/prowler_ocsf_sample.golden.json``) was generated from the
PRE-migration normalizer on main; these tests prove:

1. the normalizer still produces byte-identical output for the recorded OCSF
   sample (the frozen contract), and
2. the NEW spine path (``run_scan_and_ingest``) persists exactly the same SSOT
   rows as the LEGACY pipeline (``ingest_prowler_scan``) did — same
   fingerprints, sources, URNs, severities, attributes.

If a change legitimately needs to alter this output (it almost never should),
regenerate the golden file IN THE SAME COMMIT and explain the identity impact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    ingest_prowler_scan,
    records_to_scan_result,
)
from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
from components.shared_kernel.application.ports.scanner_port import ScanTarget
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _records():
    return json.loads((_FIXTURES / "prowler_ocsf_sample.json").read_text())


def _golden():
    return json.loads((_FIXTURES / "prowler_ocsf_sample.golden.json").read_text())


def _project(result) -> dict:
    return {
        "engine": result.engine,
        "engine_version": result.engine_version,
        "total_checks": result.total_checks,
        "passed_count": result.passed_count,
        "failed_count": result.failed_count,
        "findings": [
            {
                "source": f.source,
                "fingerprint": f.fingerprint,
                "asset_urn": f.asset_urn,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "remediation": f.remediation,
                "compliance": f.compliance,
                "attributes": f.attributes,
            }
            for f in result.findings
        ],
    }


def test_normalizer_output_matches_the_golden_master():
    """Same recorded OCSF input → byte-identical normalized output as pre-migration."""
    projected = _project(records_to_scan_result(_records(), engine_version="prowler"))
    assert json.dumps(projected, sort_keys=True) == json.dumps(_golden(), sort_keys=True)


class _StubScanner:
    def __init__(self, result):
        self._result = result

    def scan(self, target, on_progress=None):
        return self._result


def _ssot_projection(workspace) -> list[dict]:
    rows = Finding.objects.filter(workspace=workspace, source="cloud_posture.prowler").order_by("fingerprint")
    projected = []
    for f in rows:
        attributes = dict(f.attributes)
        # Run PROVENANCE is expected to differ between paths (the spine stamps
        # the ScanRun id; the legacy path has no run) — it is not identity.
        attributes.pop("scan_run_id", None)
        projected.append(
            {
                "source": f.source,
                "fingerprint": f.fingerprint,
                "asset_urn": f.asset_urn,
                "severity": f.severity,
                "status": f.status,
                "title": f.title,
                "description": f.description,
                "remediation": f.remediation,
                "compliance": f.compliance,
                "attributes": attributes,
            }
        )
    return projected


def test_spine_path_persists_identical_ssot_rows_as_the_legacy_pipeline(
    workspace_factory, django_capture_on_commit_callbacks
):
    """LEGACY ingest (workspace A) vs SPINE choreography (workspace B): the SSOT
    rows must be identical — the before/after proof for the R1 migration."""
    ws_legacy = workspace_factory()
    ws_spine = workspace_factory()

    with django_capture_on_commit_callbacks(execute=True):
        ingest_prowler_scan(workspace_id=ws_legacy.id, account_id="123456789012", records=_records())

    with django_capture_on_commit_callbacks(execute=True):
        run_scan_and_ingest(
            workspace_id=ws_spine.id,
            source="cloud_posture.prowler",
            target=ScanTarget(identifier="123456789012", params={"regions": ["us-east-1"]}),
            scanner=_StubScanner(records_to_scan_result(_records(), engine_version="prowler")),
            account_id="123456789012",
            trigger="manual",
        )

    assert _ssot_projection(ws_legacy) == _ssot_projection(ws_spine)
    assert len(_ssot_projection(ws_spine)) == 2
