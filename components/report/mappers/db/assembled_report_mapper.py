"""Serialize an :class:`AssembledReport` to/from the JSON persisted on
``Report.assembled``. Mechanical translation only — no logic.

Round-trips the honesty accounting (truncation / exclusions / sample / triage)
along with the findings. A field that this mapper forgets is a field the stored
report silently loses — which is how the curation counts went missing before.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from components.report.domain.entities.assembled_report_entity import (
    AssembledReport,
    EvidenceBlock,
    MatrixRow,
    ReportNarrative,
    SeverityHistogram,
    TechnicalFinding,
    TriageState,
)
from components.report.domain.value_objects.scan_coverage import ScanCoverage
from components.report.domain.value_objects.severity import Severity


def assembled_to_dict(a: AssembledReport) -> dict[str, Any]:
    return {
        "kind": a.kind,
        "histogram": a.histogram.counts,
        "matrix": [
            {
                "fid": r.fid,
                "category": r.category,
                "title": r.title,
                "severity": r.severity.band,
                "occurrences": r.occurrences,
                "is_sample": r.is_sample,
                "triage": _triage_to_dict(r.triage),
            }
            for r in a.matrix
        ],
        "technical_findings": [
            {
                "fid": t.fid,
                "title": t.title,
                "category": t.category,
                "severity": t.severity.band,
                "affected_asset": t.affected_asset,
                "description": t.description,
                "remediation": list(t.remediation),
                "evidence": {"lines": list(t.evidence.lines), "caption": t.evidence.caption},
                "finding_id": t.finding_id,
                "occurrences": t.occurrences,
                "is_sample": t.is_sample,
                "triage": _triage_to_dict(t.triage),
            }
            for t in a.technical_findings
        ],
        "narrative": (
            {
                "executive_summary": a.narrative.executive_summary,
                "overall_assessment": a.narrative.overall_assessment,
                "faithful": a.narrative.faithful,
                "unsupported_numbers": list(a.narrative.unsupported_numbers),
                "unsupported_names": list(a.narrative.unsupported_names),
            }
            if a.narrative
            else None
        ),
        "grounding_texts": list(a.grounding_texts),
        "raw_finding_count": a.raw_finding_count,
        "deferred_count": a.deferred_count,
        "total_matched": a.total_matched,
        "truncated_count": a.truncated_count,
        "excluded_resolved": a.excluded_resolved,
        "excluded_suppressed": a.excluded_suppressed,
        "excluded_sample": a.excluded_sample,
        "sample_finding_count": a.sample_finding_count,
        "untriaged_count": a.untriaged_count,
        "scan_coverage": _coverage_to_dict(a.scan_coverage),
    }


def _coverage_to_dict(coverage: ScanCoverage | None) -> dict[str, Any] | None:
    """``None`` round-trips as ``None`` — "we could not tell" is a real state and
    must not collapse into "nothing ran" (or, worse, into a clean result)."""
    if coverage is None:
        return None
    return {
        "completed_runs": coverage.completed_runs,
        "failed_runs": coverage.failed_runs,
        "running_runs": coverage.running_runs,
        "last_completed_at": (coverage.last_completed_at.isoformat() if coverage.last_completed_at else None),
    }


def _coverage_from_dict(data: Any) -> ScanCoverage | None:
    if not isinstance(data, dict):
        return None
    raw = data.get("last_completed_at")
    when = None
    if raw:
        try:
            when = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            when = None
    return ScanCoverage(
        completed_runs=int(data.get("completed_runs") or 0),
        failed_runs=int(data.get("failed_runs") or 0),
        running_runs=int(data.get("running_runs") or 0),
        last_completed_at=when,
    )


def _triage_to_dict(state: TriageState) -> dict[str, Any]:
    return {
        "on_board": state.on_board,
        "column": state.column,
        "team": state.team,
        "task_status": state.task_status,
        "triage_status": state.triage_status,
        "assignees": list(state.assignees),
    }


def _triage_from_dict(data: Any) -> TriageState:
    data = data or {}
    return TriageState(
        on_board=bool(data.get("on_board")),
        column=data.get("column", ""),
        team=data.get("team", ""),
        task_status=data.get("task_status", ""),
        triage_status=data.get("triage_status", ""),
        assignees=tuple(data.get("assignees") or ()),
    )


def dict_to_assembled(data: dict[str, Any]) -> AssembledReport:
    data = data or {}
    histogram = SeverityHistogram(counts=dict(data.get("histogram") or {}))
    matrix = tuple(
        MatrixRow(
            fid=row["fid"],
            category=row["category"],
            title=row["title"],
            severity=Severity(row["severity"]),
            occurrences=int(row.get("occurrences") or 1),
            is_sample=bool(row.get("is_sample")),
            triage=_triage_from_dict(row.get("triage")),
        )
        for row in data.get("matrix") or []
    )
    technicals = tuple(
        TechnicalFinding(
            fid=t["fid"],
            title=t["title"],
            category=t["category"],
            severity=Severity(t["severity"]),
            affected_asset=t["affected_asset"],
            description=t["description"],
            remediation=tuple(t.get("remediation") or ()),
            evidence=EvidenceBlock(
                lines=tuple((t.get("evidence") or {}).get("lines") or ()),
                caption=(t.get("evidence") or {}).get("caption", ""),
            ),
            finding_id=t.get("finding_id", ""),
            occurrences=int(t.get("occurrences") or 1),
            is_sample=bool(t.get("is_sample")),
            triage=_triage_from_dict(t.get("triage")),
        )
        for t in data.get("technical_findings") or []
    )
    n = data.get("narrative")
    narrative = (
        ReportNarrative(
            executive_summary=n.get("executive_summary", ""),
            overall_assessment=n.get("overall_assessment", ""),
            faithful=bool(n.get("faithful", True)),
            unsupported_numbers=tuple(n.get("unsupported_numbers") or ()),
            unsupported_names=tuple(n.get("unsupported_names") or ()),
        )
        if n
        else None
    )
    return AssembledReport(
        kind=data.get("kind", "pentest"),
        histogram=histogram,
        matrix=matrix,
        technical_findings=technicals,
        narrative=narrative,
        grounding_texts=tuple(data.get("grounding_texts") or ()),
        raw_finding_count=int(data.get("raw_finding_count") or 0),
        deferred_count=int(data.get("deferred_count") or 0),
        total_matched=int(data.get("total_matched") or 0),
        truncated_count=int(data.get("truncated_count") or 0),
        excluded_resolved=int(data.get("excluded_resolved") or 0),
        excluded_suppressed=int(data.get("excluded_suppressed") or 0),
        excluded_sample=int(data.get("excluded_sample") or 0),
        sample_finding_count=int(data.get("sample_finding_count") or 0),
        untriaged_count=int(data.get("untriaged_count") or 0),
        scan_coverage=_coverage_from_dict(data.get("scan_coverage")),
    )
