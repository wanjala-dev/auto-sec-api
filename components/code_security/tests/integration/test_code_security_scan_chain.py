"""Integration: the SAST scan chain, hermetic (ADR 0019 P1).

Stubbed engine (the recorded opengrep SARIF fixture through the real normalizer —
no k8s, no binary, no network) driven through the REAL choreography:

    run_scan_and_ingest → FindingObserved → findings SSOT (dedup on the
    line-stable fingerprint) → FindingRaised → board card at the severity floor
    → RepoScanSnapshot post-ingest row.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from components.agents.application.handlers.finding_raised_board_handler import (
    handle_finding_raised_board,
)
from components.code_security.application.providers.snapshot_provider import (
    persist_repo_scan_snapshot,
)
from components.code_security.infrastructure.services.opengrep_normalizer import (
    opengrep_sarif_to_scan_result,
)
from components.findings.application.handlers.finding_observed_handler import (
    handle_finding_observed,
)
from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
from components.shared_kernel.application.ports.scanner_port import ScanTarget
from components.shared_kernel.domain.events import FindingObserved, FindingRaised, ScanCompleted
from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.project.models import Task

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "code_security.opengrep"
_REPO = "wanjala-dev/auto-sec-api"
_SHA = "c" * 40
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "opengrep_corpus.sarif.json"


class _StubOpengrepScanner:
    """The real normalizer over the real recorded SARIF — only the Job is stubbed."""

    def scan(self, target, on_progress=None):
        sarif = json.loads(_FIXTURE.read_text())
        return opengrep_sarif_to_scan_result(sarif, repo=_REPO, commit_sha=_SHA)


class _CapturingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def _run_scan(ws, publisher):
    return run_scan_and_ingest(
        workspace_id=ws.id,
        source=_SOURCE,
        target=ScanTarget(identifier=_REPO, credentials={"token": "t", "commit_sha": _SHA}),
        scanner=_StubOpengrepScanner(),
        event_publisher=publisher,
    )


def _ingest_to_ssot(publisher):
    for event in publisher.published:
        if isinstance(event, FindingObserved):
            handle_finding_observed(event)


def test_scan_lands_findings_in_the_ssot_with_code_locations(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    publisher = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        run = _run_scan(ws, publisher)
    _ingest_to_ssot(publisher)

    observed = [e for e in publisher.published if isinstance(e, FindingObserved)]
    completed = [e for e in publisher.published if isinstance(e, ScanCompleted)]
    assert len(observed) == 20
    assert len(completed) == 1, "exactly ONE digest signal per scan run"
    assert completed[0].critical == 0, "the P1 pack never mints criticals"

    rows = Finding.objects.filter(workspace_id=ws.id, source=_SOURCE)
    assert rows.count() == 20
    sample = rows.filter(fingerprint__contains="jwt-verify-disabled|corpus/vuln.py").first()
    assert sample is not None
    assert sample.attributes["path"] == "corpus/vuln.py"
    assert sample.attributes["start_line"] > 0
    assert "jwt.decode" in sample.attributes["snippet"]
    assert sample.attributes["commit_sha"] == _SHA
    assert run.failed_count == 20


def test_second_scan_dedupes_to_zero_new_findings(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    first = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        _run_scan(ws, first)
    _ingest_to_ssot(first)
    baseline = list(Finding.objects.filter(workspace_id=ws.id, source=_SOURCE).values_list("id", "first_seen_at"))

    second = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        _run_scan(ws, second)
    _ingest_to_ssot(second)

    rows = Finding.objects.filter(workspace_id=ws.id, source=_SOURCE)
    assert rows.count() == 20, "re-scan converges on the same fingerprints — 0 new findings"
    assert sorted(baseline) == sorted(rows.values_list("id", "first_seen_at")), (
        "identity + first_seen survive a re-scan"
    )


def test_snapshot_row_persisted_with_commit_provenance(workspace_factory):
    ws = workspace_factory()
    from infrastructure.persistence.code_security.models import RepoScanSnapshot

    result = _StubOpengrepScanner().scan(None)
    # re-attach the scan_meta artifact exactly as the real adapter does
    from components.shared_kernel.application.ports.scanner_port import ScanArtifact, ScanResult

    result = ScanResult(
        findings=result.findings,
        engine=result.engine,
        engine_version=result.engine_version,
        total_checks=result.total_checks,
        passed_count=0,
        failed_count=result.failed_count,
        artifacts=(
            ScanArtifact(
                kind="code_security.scan_meta",
                media_type="application/json",
                content=json.dumps({"repo": _REPO, "commit_sha": _SHA, "engine_version": "1.26.0"}),
            ),
        ),
    )
    run_id = uuid4()
    persist_repo_scan_snapshot(run_id=run_id, workspace_id=ws.id, target_ref=_REPO, result=result)
    persist_repo_scan_snapshot(run_id=run_id, workspace_id=ws.id, target_ref=_REPO, result=result)  # idempotent

    row = RepoScanSnapshot.objects.get(scan_run_id=run_id)
    assert row.repo == _REPO
    assert row.commit_sha == _SHA
    assert row.total_findings == 20
    assert row.critical_count == 0
    assert row.high_count > 0
    assert RepoScanSnapshot.objects.filter(workspace_id=ws.id).count() == 1


def _raised(finding_row) -> FindingRaised:
    return FindingRaised(
        workspace_id=finding_row.workspace_id,
        finding_id=finding_row.id,
        fingerprint=finding_row.fingerprint,
        asset_urn=finding_row.asset_urn,
        severity=finding_row.severity,
        status=finding_row.status,
        source=finding_row.source,
        title=finding_row.title,
        is_new=True,
    )


def test_board_card_created_at_the_severity_floor(workspace_factory, django_capture_on_commit_callbacks):
    """HIGH findings become cards; MEDIUM stay SSOT-only (D4 floor, default high+critical).

    The SSOT ingest already runs the real event bus, so ``handle_finding_observed``
    → ``FindingRaised`` → the board handler fires per finding — the cards created
    here ARE the production path, not a hand-driven simulation.
    """
    ws = workspace_factory()
    publisher = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        _run_scan(ws, publisher)
    _ingest_to_ssot(publisher)

    high_count = Finding.objects.filter(workspace_id=ws.id, source=_SOURCE, severity="high").count()
    medium = Finding.objects.filter(workspace_id=ws.id, source=_SOURCE, severity="medium").first()
    assert high_count > 0 and medium is not None

    cards = Task.objects.filter(workspace=ws, source_type="ai.code_security")
    assert cards.count() == high_count, "one card per HIGH finding, none for MEDIUM/LOW"
    severities = {card.metadata["payload"]["severity"] for card in cards}
    assert severities == {"high"}, "the floor keeps sub-high findings SSOT-only"

    # An explicit re-raise of a below-floor finding still creates nothing, and a
    # re-raise of an existing card is idempotent (same lookup_key → no dup).
    handle_finding_raised_board(_raised(medium))
    high = Finding.objects.filter(workspace_id=ws.id, source=_SOURCE, severity="high").first()
    handle_finding_raised_board(_raised(high))
    assert Task.objects.filter(workspace=ws, source_type="ai.code_security").count() == high_count

    card = cards.filter(metadata__payload__finding_id=str(high.id)).first()
    assert card is not None
    # P2: the card is ROUTED to the SAST specialist (P1 filed it operator-reading).
    # The routing entry and the specialist's triage tool shipped together — a
    # routable source with no tool is a silent no-op.
    assert card.metadata["agent_type"] == "code_security_agent"
    assert card.metadata["payload"]["rule_id"]
    assert card.metadata["payload"]["path"]
    # The matched region rides the card so the advisor + HUD callout can ground on it.
    assert "snippet" in card.metadata["payload"]
    assert ":" in card.title  # rule — path:line copy


class _FilteredOpengrepScanner:
    """The stub scanner minus one rule — simulates a rescan AFTER a fix merged
    (the fixed finding is simply no longer observed)."""

    def __init__(self, *, drop_rule: str):
        self._drop_rule = drop_rule

    def scan(self, target, on_progress=None):
        sarif = json.loads(_FIXTURE.read_text())
        for run in sarif.get("runs", []):
            run["results"] = [r for r in run.get("results", []) if self._drop_rule not in str(r.get("ruleId", ""))]
        return opengrep_sarif_to_scan_result(sarif, repo=_REPO, commit_sha=_SHA)


def test_rescan_without_the_fixed_finding_leaves_it_resolved(workspace_factory, django_capture_on_commit_callbacks):
    """The #118 rescan outcome flows the EXISTING lifecycle unchanged: the merged
    fix's finding was resolved by the reconciler; the verification rescan simply
    no longer observes it — nothing reopens it (re-observation is what reopens a
    terminal finding), while the still-present findings are re-observed."""
    from django.utils import timezone as dj_timezone

    from components.findings.application.commands.change_finding_status_command import (
        ChangeFindingStatusCommand,
    )
    from components.findings.application.providers.finding_provider import FindingProvider

    ws = workspace_factory()
    first = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        _run_scan(ws, first)
    _ingest_to_ssot(first)

    fixed_rows = list(Finding.objects.filter(workspace_id=ws.id, fingerprint__contains="jwt-verify-disabled|"))
    assert fixed_rows, "the fixture must observe the rule we are about to fix"
    # The reconciler resolved the finding(s) when the draft PR merged (existing path).
    for row in fixed_rows:
        FindingProvider.build_change_finding_status_use_case().execute(
            ChangeFindingStatusCommand(
                workspace_id=ws.id, finding_id=row.id, action="resolve", at=dj_timezone.now(), actor_id="reconciler"
            )
        )

    # The verification rescan: same repo, the fixed finding absent from the results.
    second = _CapturingPublisher()
    with django_capture_on_commit_callbacks(execute=True):
        run = run_scan_and_ingest(
            workspace_id=ws.id,
            source=_SOURCE,
            target=ScanTarget(identifier=_REPO, credentials={"token": "t", "commit_sha": _SHA}),
            scanner=_FilteredOpengrepScanner(drop_rule="jwt-verify-disabled"),
            event_publisher=second,
        )
    _ingest_to_ssot(second)

    for row in fixed_rows:
        row.refresh_from_db()
        assert row.status == "resolved", "not re-observed → the existing lifecycle keeps it closed"
    assert run.failed_count == 20 - len(fixed_rows), "the rescan genuinely lacked the fixed finding(s)"
    # The records are retained (no hard delete) and the sibling findings are still open.
    assert Finding.objects.filter(workspace_id=ws.id, source=_SOURCE).count() == 20
    assert Finding.objects.filter(workspace_id=ws.id, source=_SOURCE, status="open").count() == 20 - len(fixed_rows)
