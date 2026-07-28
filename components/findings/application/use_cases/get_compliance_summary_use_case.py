"""Compute the workspace's compliance posture summary (CQRS read).

Reads the compliance tag bags of every open finding through the store port, then hands
them to the pure ``compliance_summary`` builder for the per-framework failing-control
roll-up. One indexed read; no mutation, no fabricated pass %.
"""

from __future__ import annotations

from uuid import UUID

from components.findings.domain.services.compliance_summary import ComplianceSummary, build


class GetComplianceSummaryUseCase:
    def __init__(self, *, finding_store) -> None:
        self._findings = finding_store

    def execute(self, workspace_id: UUID) -> ComplianceSummary:
        bags = self._findings.open_finding_compliance(workspace_id)
        return build(bags)
