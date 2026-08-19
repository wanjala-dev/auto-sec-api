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
    TriageState,
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

# SSOT ``Finding.source`` prefix → category. The SSOT names pillars
# (``cloud_posture.prowler``, ``code_security.opengrep``), where the board named
# detector actions — longest prefix wins so ``logwatch.optimization`` does not
# resolve as ``logwatch``.
_CATEGORY_BY_SOURCE: dict[str, str] = {
    "cloud_posture": "Cloud Posture",
    "cloud_graph": "Cloud Exposure",
    "container_security": "Container Security",
    "code_security": "Code Security",
    "logwatch.optimization": "Resource Optimization",
    "logwatch": "Log Anomaly",
    "iam": "Identity and Access",
}


def _category_from_source(source: str) -> str:
    """Category for an SSOT source, or ``""`` when the source is unrecognised.

    A ``sample.`` finding is categorised by what it is a sample OF — the demo
    dataset is labelled as sample data on the finding itself (``is_sample``), so
    the category stays useful rather than collapsing every demo row into "Sample".
    """
    cleaned = str(source or "").strip().lower()
    if cleaned.startswith("sample."):
        cleaned = cleaned[len("sample.") :]
    for prefix in sorted(_CATEGORY_BY_SOURCE, key=len, reverse=True):
        if cleaned.startswith(prefix):
            return _CATEGORY_BY_SOURCE[prefix]
    return ""


def _finding_category(finding: Mapping[str, Any]) -> str:
    """Human category from the finding's source, then action_type / detector."""
    from_source = _category_from_source(finding.get("source") or "")
    if from_source:
        return from_source
    meta = finding.get("metadata") or {}
    action = str(meta.get("action_type") or "")
    for key, label in _CATEGORY_BY_ACTION.items():
        if action.startswith(key):
            return label
    detector = str(meta.get("detector") or "").strip()
    if detector:
        return detector.replace("_", " ").title()
    return "Other"


def finding_severity(finding: Mapping[str, Any]) -> Severity:
    """The finding's band, read top-level first.

    ``severity`` is a first-class key on the port's mapping (both adapters set
    it); the ``metadata`` fallback keeps a hand-built board finding working.
    """
    raw = finding.get("severity")
    if not raw:
        raw = (finding.get("metadata") or {}).get("severity")
    return Severity(normalize_band(raw))


def _triage_state(finding: Mapping[str, Any]) -> TriageState:
    """The board enrichment, or the explicit untriaged state."""
    triage = finding.get("triage") or {}
    if not triage.get("on_board"):
        return TriageState(on_board=False)
    return TriageState(
        on_board=True,
        column=str(triage.get("column") or ""),
        team=str(triage.get("team") or ""),
        task_status=str(triage.get("task_status") or ""),
        triage_status=str(triage.get("triage_status") or ""),
        assignees=tuple(str(a) for a in (triage.get("assignees") or []) if str(a).strip()),
    )


def _affected_asset(payload: Mapping[str, Any]) -> str:
    """The system the finding implicates.

    An SSOT finding names its asset canonically (``AssetUrn``), which is the most
    precise answer available and is preferred; a board finding falls back to the
    monitored service plus the blast-radius log level/window.
    """
    asset_urn = str(payload.get("asset_urn") or "").strip()
    if asset_urn:
        return asset_urn
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
    title = str(meta.get("ai_headline") or finding.get("title") or "Untitled finding").strip()
    return TechnicalFinding(
        fid=fid,
        title=title,
        category=_finding_category(finding),
        severity=finding_severity(finding),
        affected_asset=_affected_asset(payload),
        description=_description(finding, payload),
        remediation=_remediation(payload),
        evidence=_evidence_block(finding, payload),
        finding_id=str(finding.get("id") or ""),
        occurrences=max(1, int(occurrences)),
        triage=_triage_state(finding),
        is_sample=bool(finding.get("is_sample")),
    )


def build_matrix_row(technical: TechnicalFinding) -> MatrixRow:
    """The §3 matrix row for an already-built technical finding."""
    return MatrixRow(
        fid=technical.fid,
        category=technical.category,
        title=technical.title,
        severity=technical.severity,
        occurrences=technical.occurrences,
        triage=technical.triage,
        is_sample=technical.is_sample,
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
    title = str(meta.get("ai_headline") or finding.get("title") or "")
    return (finding_severity(finding).rank, title.lower())
