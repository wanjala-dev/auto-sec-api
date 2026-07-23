"""Serialize an :class:`AssembledReport` to/from the JSON persisted on
``Report.assembled``. Mechanical translation only — no logic."""

from __future__ import annotations

from typing import Any

from components.report.domain.entities.assembled_report_entity import (
    AssembledReport,
    EvidenceBlock,
    MatrixRow,
    ReportNarrative,
    SeverityHistogram,
    TechnicalFinding,
)
from components.report.domain.value_objects.severity import Severity


def assembled_to_dict(a: AssembledReport) -> dict[str, Any]:
    return {
        "kind": a.kind,
        "histogram": a.histogram.counts,
        "matrix": [
            {"fid": r.fid, "category": r.category, "title": r.title, "severity": r.severity.band} for r in a.matrix
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
    }


def dict_to_assembled(data: dict[str, Any]) -> AssembledReport:
    data = data or {}
    histogram = SeverityHistogram(counts=dict(data.get("histogram") or {}))
    matrix = tuple(
        MatrixRow(
            fid=row["fid"],
            category=row["category"],
            title=row["title"],
            severity=Severity(row["severity"]),
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
    )
