"""Deterministic finding → technical-section mapping.

Turns one board finding (the plain dict the assembler hands in — the shape of
``Task`` fields + ``Task.metadata``) into a :class:`TechnicalFinding` and a
:class:`MatrixRow`, and a whole list into a :class:`SeverityHistogram`. NO LLM,
NO ORM, NO Django — the assembler reads the ORM and passes dicts in; this module
only shapes the deliverable data.

The mapping is grounded in the real finding payload shapes produced by the log
detectors (``components/integrations/application/log_ingest_service.py`` and
``log_pattern_analyzer_service.py``):

    metadata = {
        "severity": "high",                    # band
        "ai_headline": "...", "ai_narrative": "...",
        "detector": "logwatch", "action_type": "log_watch.error",
        "payload": {
            "signal": "one-line what tripped",
            "service": "auth-svc",             # → affected asset
            "level": "ERROR",
            "evidence": [{"type": "log_line", "detail": "..."}],   # → evidence block
            "blast_radius": {"service": "...", "level": "...", "window_records": 42},
            "confidence": "high",
            "probable_cause": "...", "suggested_fix": "...", "recommendation": "...",
            "frequency": {"last_window": 88, ...},   # optimization findings only
            "signature": "...", "subject": "...",     # optimization findings only
        },
    }

Everything is best-effort: a missing field never raises — it degrades to an
honest placeholder so a sparse finding still renders a coherent section.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from components.report.domain.entities.assembled_report_entity import (
    EvidenceBlock,
    MatrixRow,
    SeverityHistogram,
    TechnicalFinding,
)
from components.report.domain.value_objects.severity import (
    SEVERITY_ORDER,
    Severity,
    normalize_band,
)

# Detector/action → human category label for the §3 matrix + §4 section.
_CATEGORY_BY_ACTION: dict[str, str] = {
    "log_watch": "Log Anomaly",
    "log_optimization": "Resource Optimization",
    "cloud_posture": "Cloud Posture",
    "agent_run_quality": "Detection Quality",
}


def _finding_category(finding: Mapping[str, Any]) -> str:
    """Human category from the finding's action_type / detector."""
    meta = finding.get("metadata") or {}
    action = str(meta.get("action_type") or "")
    for key, label in _CATEGORY_BY_ACTION.items():
        if action.startswith(key):
            return label
    detector = str(meta.get("detector") or "").strip()
    if detector:
        return detector.replace("_", " ").title()
    return "Other"


def _affected_asset(payload: Mapping[str, Any]) -> str:
    """The system the finding implicates — the monitored service, plus the
    blast-radius log level/window when present."""
    service = str(payload.get("service") or "").strip()
    blast = payload.get("blast_radius") or {}
    level = str(blast.get("level") or "").strip()
    records = blast.get("window_records")
    parts = [service] if service else []
    tail = []
    if level:
        tail.append(level)
    if records:
        tail.append(f"{records} records")
    if tail:
        parts.append(f"({', '.join(tail)})")
    return " ".join(parts) if parts else "Not specified"


def _description(finding: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """The narrative description — the detector's own narrative + the one-line
    signal + probable cause, joined into prose. All grounded, no invention."""
    meta = finding.get("metadata") or {}
    chunks: list[str] = []
    narrative = str(meta.get("ai_narrative") or finding.get("description") or "").strip()
    signal = str(payload.get("signal") or "").strip()
    cause = str(payload.get("probable_cause") or "").strip()
    if narrative:
        chunks.append(narrative)
    if signal and signal not in narrative:
        chunks.append(signal)
    if cause:
        chunks.append(f"Probable cause: {cause}")
    return "\n\n".join(chunks) if chunks else "No description was recorded for this finding."


def _remediation(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Recommended-remediation bullets from the triage suggestion fields."""
    bullets: list[str] = []
    for key in ("recommendation", "suggested_fix"):
        val = str(payload.get(key) or "").strip()
        if val and val not in bullets:
            bullets.append(val)
    if not bullets:
        bullets.append(
            "No automated remediation was suggested for this finding — review the evidence and "
            "determine the appropriate corrective action."
        )
    return tuple(bullets)


def _evidence_block(finding: Mapping[str, Any], payload: Mapping[str, Any]) -> EvidenceBlock:
    """The dark terminal block — the detector's literal evidence lines."""
    lines: list[str] = []
    service = str(payload.get("service") or "").strip()
    if service:
        lines.append(f"SERVICE  {service}")
    level = str(payload.get("level") or "").strip()
    if level:
        lines.append(f"LEVEL    {level}")
    freq = payload.get("frequency") or {}
    if isinstance(freq, Mapping) and freq:
        pretty = ", ".join(f"{k}={v}" for k, v in freq.items())
        lines.append(f"FREQUENCY  {pretty}")
    evidence = payload.get("evidence") or []
    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes)):
        for item in evidence:
            if isinstance(item, Mapping):
                etype = str(item.get("type") or "evidence").upper()
                detail = str(item.get("detail") or "").strip()
                if detail:
                    lines.append(f"{etype}  {detail}")
            elif item:
                lines.append(str(item))
    confidence = str(payload.get("confidence") or "").strip()
    caption_bits = []
    meta = finding.get("metadata") or {}
    if confidence:
        caption_bits.append(f"detector confidence: {confidence}")
    if (meta.get("triage") or {}).get("needs_human"):
        caption_bits.append("flagged for human review")
    caption = "; ".join(caption_bits)
    if not lines:
        lines.append("No structured evidence was captured for this finding.")
    return EvidenceBlock(lines=tuple(lines), caption=caption)


def build_technical_finding(finding: Mapping[str, Any], *, fid: str, occurrences: int = 1) -> TechnicalFinding:
    """Map one finding dict into its full §4 technical section.

    ``occurrences`` is how many raw findings this representative stands for after
    dedup (see :mod:`finding_curation`); it is carried through so the deliverable
    can state the true observed volume.
    """
    meta = finding.get("metadata") or {}
    payload = meta.get("payload") or {}
    severity = Severity(normalize_band(meta.get("severity")))
    title = str(meta.get("ai_headline") or finding.get("title") or "Untitled finding").strip()
    return TechnicalFinding(
        fid=fid,
        title=title,
        category=_finding_category(finding),
        severity=severity,
        affected_asset=_affected_asset(payload),
        description=_description(finding, payload),
        remediation=_remediation(payload),
        evidence=_evidence_block(finding, payload),
        finding_id=str(finding.get("id") or ""),
        occurrences=max(1, int(occurrences)),
    )


def build_matrix_row(technical: TechnicalFinding) -> MatrixRow:
    """The §3 matrix row for an already-built technical finding."""
    return MatrixRow(
        fid=technical.fid,
        category=technical.category,
        title=technical.title,
        severity=technical.severity,
        occurrences=technical.occurrences,
    )


def build_histogram(technicals: Iterable[TechnicalFinding]) -> SeverityHistogram:
    """Count findings per severity band."""
    counts = dict.fromkeys(SEVERITY_ORDER, 0)
    for tech in technicals:
        counts[tech.severity.band] += 1
    return SeverityHistogram(counts=counts)


def sort_key(finding: Mapping[str, Any]) -> tuple[int, str]:
    """Sort findings most-severe first, then by title — deterministic FID
    assignment (F-01 is the most severe)."""
    meta = finding.get("metadata") or {}
    sev = Severity(normalize_band(meta.get("severity")))
    title = str(meta.get("ai_headline") or finding.get("title") or "")
    return (sev.rank, title.lower())
