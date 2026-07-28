"""Output DTO — the compliance posture summary for the HUD Compliance card."""

from __future__ import annotations

from components.findings.domain.services.compliance_summary import ComplianceSummary


class ComplianceSummaryResource:
    @staticmethod
    def of(summary: ComplianceSummary) -> dict:
        # {frameworks:[{name, failing_controls}], frameworks_with_failures,
        #  total_failing_controls} — distinct failing controls per curated framework.
        return summary.to_dict()
