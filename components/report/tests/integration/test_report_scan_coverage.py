"""A report may only claim "no findings" when a scan actually looked.

The defect this guards (QA provenance sweep, 2026-08-19): a workspace that had
NEVER been scanned rendered a deliverable asserting

    "No findings were surfaced in the scope reviewed."
    "No technical findings were surfaced in the scope reviewed."

with a Critical/High/Medium/Low/Informational histogram of zeros — byte-identical
to the report of a workspace that was scanned thoroughly and is genuinely clean.
The same document rendered when every scan in the period had FAILED (the live
cluster carried 6 failed runs at the time). A report is an evidence artifact that
leaves the building; an absence of data presented as a clean result is the
highest-severity provenance falsehood this product can make.

The fix is not to make the claim true — it is to only make it when it is. These
tests pin both halves: the empty-and-uncovered report must NOT read clean, and
the genuinely-covered clean report must still read clean.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from components.report.application.ports.finding_source_port import ScanCoverage
from components.report.domain.entities.assembled_report_entity import (
    AssembledReport,
    SeverityHistogram,
)
from components.report.infrastructure.adapters.report_html_builder import build_report_html

pytestmark = pytest.mark.integration

_WS = "00000000-0000-0000-0000-0000000000ff"


def _empty(coverage: ScanCoverage | None) -> AssembledReport:
    return AssembledReport(
        kind="pentest",
        histogram=SeverityHistogram(counts={"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}),
        matrix=(),
        technical_findings=(),
        scan_coverage=coverage,
    )


def _render(assembled: AssembledReport) -> str:
    return build_report_html(
        assembled=assembled,
        kind="pentest",
        title="Security Assessment",
        scope={},
        workspace_id=_WS,
        workspace_name="[QA] coverage probe",
        workspace_logo_url="",
    )


class TestEmptyReportDoesNotReadClean:
    def test_never_scanned_workspace_does_not_claim_a_clean_result(self):
        """Zero findings + zero completed scans must never render as "no findings"."""
        html = _render(_empty(ScanCoverage(completed_runs=0, failed_runs=0, running_runs=0)))

        assert "No findings were surfaced in the scope reviewed." not in html
        assert "No technical findings were surfaced in the scope reviewed." not in html
        # It must say plainly WHY the report is empty.
        assert "No completed scan covers this scope" in html
        assert "not a clean result" in html

    def test_all_scans_failed_is_stated_even_though_findings_are_zero(self):
        html = _render(_empty(ScanCoverage(completed_runs=0, failed_runs=6, running_runs=0)))

        assert "No findings were surfaced in the scope reviewed." not in html
        assert "6 scans failed" in html

    def test_failed_scans_are_stated_even_when_findings_were_found(self):
        """An incomplete assessment is incomplete whatever the finding count."""
        covered = AssembledReport(
            kind="pentest",
            histogram=SeverityHistogram(counts={"critical": 0, "high": 2, "medium": 0, "low": 0}),
            matrix=(),
            technical_findings=(),
            total_matched=2,
            scan_coverage=ScanCoverage(completed_runs=3, failed_runs=2, running_runs=0),
        )
        html = _render(covered)
        assert "2 scans failed" in html

    def test_genuinely_scanned_and_clean_still_reads_clean(self):
        """The honest clean result must keep its claim — this fix removes a false
        claim, it does not remove a true one."""
        html = _render(
            _empty(
                ScanCoverage(
                    completed_runs=4,
                    failed_runs=0,
                    running_runs=0,
                    last_completed_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
                )
            )
        )

        assert "No findings were surfaced in the scope reviewed." in html
        assert "No completed scan covers this scope" not in html
        # …and it says what backs the claim.
        assert "4 scans completed" in html

    def test_unreported_coverage_never_asserts_a_clean_result(self):
        """An adapter that cannot report coverage (the board-only lens) must not
        have its silence read as "we scanned and found nothing"."""
        html = _render(_empty(None))

        assert "No completed scan covers this scope" not in html
        assert "Scan coverage for this scope was not recorded" in html


class TestCoverageReachesTheNarrativeGrounding:
    def test_no_coverage_is_in_the_grounding_corpus(self):
        """The narrative writer is grounded ONLY in this corpus. If the corpus
        says nothing but zeros, the LLM writes "no vulnerabilities were found"."""
        from components.report.application.services.report_assembler_service import (
            build_grounding_texts,
        )

        texts = build_grounding_texts(
            histogram=SeverityHistogram(counts={"critical": 0, "high": 0}),
            featured=(),
            distinct_count=0,
            raw_count=0,
            deferred_count=0,
            scan_coverage=ScanCoverage(completed_runs=0, failed_runs=2, running_runs=0),
        )
        corpus = " ".join(texts)
        assert "no completed scan" in corpus.lower()
        assert "2" in corpus

    def test_covered_corpus_states_the_coverage(self):
        from components.report.application.services.report_assembler_service import (
            build_grounding_texts,
        )

        texts = build_grounding_texts(
            histogram=SeverityHistogram(counts={"critical": 0}),
            featured=(),
            distinct_count=0,
            raw_count=0,
            deferred_count=0,
            scan_coverage=ScanCoverage(completed_runs=5, failed_runs=0, running_runs=0),
        )
        assert any("5" in t and "completed" in t.lower() for t in texts)
