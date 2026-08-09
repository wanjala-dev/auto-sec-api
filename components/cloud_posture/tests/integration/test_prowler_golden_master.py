"""Golden master: the spine migration must not move a single AWS byte.

Finding identity is ``(workspace, source, fingerprint)`` and dedup continuity is
customer-facing — a fingerprint or URN change re-opens every existing finding
as a duplicate. The golden fixture
(``fixtures/prowler_ocsf_sample.golden.json``) was generated from the
PRE-migration normalizer on main; these tests prove:

1. the normalizer still produces byte-identical output for the recorded OCSF
   sample (the frozen contract), and
2. the spine path (``run_scan_and_ingest``) persists SSOT rows exactly equal
   to the golden findings — same fingerprints, sources, URNs, severities,
   attributes. (The legacy pipeline this was originally diffed against is
   deleted; the golden file IS its recorded output.)

If a change legitimately needs to alter this output (it almost never should),
regenerate the golden file IN THE SAME COMMIT and explain the identity impact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
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


def test_spine_path_persists_exactly_the_golden_findings(workspace_factory, django_capture_on_commit_callbacks):
    """The SPINE choreography persists SSOT rows whose identity/content equal the
    golden fixture's findings — the frozen before/after proof for the R1
    migration (the legacy ingest pipeline this was originally compared against
    is deleted; the golden file IS its recorded output)."""
    ws = workspace_factory()

    with django_capture_on_commit_callbacks(execute=True):
        run_scan_and_ingest(
            workspace_id=ws.id,
            source="cloud_posture.prowler",
            target=ScanTarget(identifier="123456789012", params={"regions": ["us-east-1"]}),
            scanner=_StubScanner(records_to_scan_result(_records(), engine_version="prowler")),
            account_id="123456789012",
            trigger="manual",
        )

    persisted = _ssot_projection(ws)
    expected = sorted(_golden()["findings"], key=lambda f: f["fingerprint"])
    assert len(persisted) == 2
    for row, gold in zip(persisted, expected, strict=True):
        assert row["source"] == gold["source"]
        assert row["fingerprint"] == gold["fingerprint"]
        assert row["asset_urn"] == gold["asset_urn"]
        assert row["severity"] == gold["severity"]
        assert row["title"] == gold["title"]
        assert row["description"] == gold["description"]
        assert row["remediation"] == gold["remediation"]
        assert row["compliance"] == gold["compliance"]
        assert row["attributes"] == gold["attributes"]
        assert row["status"] == "open"
