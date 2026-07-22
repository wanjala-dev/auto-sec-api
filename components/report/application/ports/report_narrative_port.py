"""Port: write the grounded narrative sections over assembled findings.

The narrative writer produces ONLY the two prose sections a human analyst would
write — the executive summary and the overall-assessment theme — and NOTHING
that introduces a finding, number, or system not already in the assembled data.
The adapter enforces that with the faithfulness verifier: any figure the prose
states that is not grounded in the assembler's corpus is surfaced, and the prose
is regenerated or the report is flagged — never silently shipped.

The assembler is the assessor; this port is the assessor's scribe.
"""

from __future__ import annotations

import abc

from components.report.domain.entities.assembled_report import AssembledReport, ReportNarrative


class ReportNarrativePort(abc.ABC):
    @abc.abstractmethod
    def write(
        self,
        *,
        assembled: AssembledReport,
        workspace_name: str,
        engagement_title: str,
        scope_summary: str,
    ) -> ReportNarrative:
        """Return the grounded exec-summary + overall-assessment prose.

        MUST NOT introduce any finding not present in ``assembled``. The result
        carries the faithfulness verdict so the caller can gate on it.
        """
        raise NotImplementedError
