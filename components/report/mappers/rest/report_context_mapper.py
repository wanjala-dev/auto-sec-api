"""Map an assembled report + workspace brand into the template render context.

The cover brand is the WORKSPACE ORG identity (name + logo + colours), resolved
via ``resolve_brand_colors`` + the workspace ``photo_url`` (falling back to the
default Octopus mark). The assessed target/scope is data the operator supplied —
never confused with the vendor identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from components.report.domain.entities.assembled_report_entity import AssembledReport
from components.report.domain.report_kind import get_report_kind
from components.report.domain.value_objects.severity import SEVERITY_ORDER, band_color, band_meaning


def build_render_context(
    *,
    assembled: AssembledReport,
    kind: str,
    title: str,
    scope: dict[str, Any],
    workspace_id: str,
    workspace_name: str,
    workspace_logo_url: str,
) -> dict[str, Any]:
    from components.shared_platform.application.providers.pdf_brand_assets_provider import (
        DEFAULT_BRAND_DATA_URI,
        resolve_brand_colors,
    )

    spec = get_report_kind(kind)
    brand = resolve_brand_colors(workspace_id)
    logo = (workspace_logo_url or "").strip() or DEFAULT_BRAND_DATA_URI

    narrative = assembled.narrative
    now = datetime.now(UTC)

    histogram = [
        {
            "band": band,
            "label": band.capitalize(),
            "count": count,
            "color": band_color(band),
            # Bar width capped so a huge count doesn't overflow the page.
            "bar_units": min(count, 40),
        }
        for band, count in assembled.histogram.ordered()
    ]

    matrix = [
        {
            "fid": row.fid,
            "category": row.category,
            "title": row.title,
            "severity": row.severity.label,
            "severity_color": row.severity.color,
            "cvss": f"{row.cvss:.1f}",
            "occurrences": row.occurrences,
            # "×320" chip when a row stands for a collapsed cluster; "" when unique.
            "occurrence_label": f"×{row.occurrences}" if row.occurrences > 1 else "",
            "triage": row.triage.label,
            "is_sample": row.is_sample,
        }
        for row in assembled.matrix
    ]

    technical = [
        {
            "fid": tech.fid,
            "title": tech.title,
            "category": tech.category,
            "severity": tech.severity.label,
            "severity_color": tech.severity.color,
            "cvss": f"{tech.cvss:.1f}",
            "affected_asset": tech.affected_asset,
            "occurrences": tech.occurrences,
            "occurrence_label": f"Observed {tech.occurrences} times" if tech.occurrences > 1 else "",
            "description_paragraphs": [p for p in tech.description.split("\n\n") if p.strip()],
            "remediation": list(tech.remediation),
            "evidence_lines": list(tech.evidence.lines),
            "evidence_caption": tech.evidence.caption,
            "triage": tech.triage.label,
            "triage_untriaged": not tech.triage.on_board,
            "is_sample": tech.is_sample,
        }
        for tech in assembled.technical_findings
    ]

    severity_ratings = [
        {"band": band.capitalize(), "color": band_color(band), "meaning": band_meaning(band)} for band in SEVERITY_ORDER
    ]

    return {
        # ── Brand (workspace org identity) ──
        "brand_primary": brand["primary_light"],
        "brand_primary_deep": brand["primary_deep"],
        "brand_primary_soft": brand["primary_soft"],
        "brand_secondary": brand["secondary"],
        "font_heading": brand["font_heading_stack"],
        "font_body": brand["font_body_stack"],
        "workspace_name": workspace_name or "Security Assessment",
        "workspace_logo": logo,
        # ── Cover / meta ──
        "report_title": spec.title,
        "document_title": title or spec.title,
        "scope_subtitle": scope.get("scope_summary") or "Security Assessment",
        "client_name": scope.get("client_name") or (scope.get("target") or workspace_name or "Client"),
        "prepared_by": workspace_name or "Security Team",
        "date_label": now.strftime("%B %Y"),
        "confidentiality": spec.confidentiality,
        "section_order": list(spec.section_order),
        # ── Scope / approach ──
        "target": scope.get("target") or scope.get("scope_summary") or "The systems in scope for this engagement.",
        "approach": scope.get("approach")
        or "A grounded review of the findings surfaced by the platform's detection pipeline.",
        # ── Narrative ──
        "executive_summary": _paragraphs(narrative.executive_summary if narrative else ""),
        "overall_assessment": _paragraphs(narrative.overall_assessment if narrative else ""),
        "narrative_faithful": (narrative.faithful if narrative else True),
        "narrative_unsupported": list(narrative.unsupported_numbers) if narrative else [],
        # ── Findings ──
        # finding_total is the DISTINCT-issue count (post-dedup) — what the report
        # is really about. raw_finding_total is the pre-dedup observed volume.
        "finding_total": assembled.distinct_finding_count,
        "raw_finding_total": assembled.raw_finding_count,
        "deferred_count": assembled.deferred_count,
        "detailed_count": len(technical),
        # Shown under §4 when lower-severity findings are matrix-only, so the
        # reader knows the technical section is curated, not truncated silently.
        "deferred_note": (
            f"{assembled.deferred_count} additional lower-severity finding"
            f"{'s' if assembled.deferred_count != 1 else ''} "
            f"{'are' if assembled.deferred_count != 1 else 'is'} listed in the Findings Matrix (§3); "
            f"full technical detail is provided for the {len(technical)} most significant "
            f"finding{'s' if len(technical) != 1 else ''}."
        )
        if assembled.deferred_count
        else "",
        # ── Honesty notices (see the assembler: nothing is dropped in silence) ──
        # A report is an artifact that leaves the building. If it contains seeded
        # demo data, or if the scope limit cut findings off, or if findings were
        # excluded by policy, the DOCUMENT says so — it is not left to whoever
        # forwards the PDF to work it out.
        "contains_sample_data": assembled.contains_sample_data,
        "sample_finding_count": assembled.sample_finding_count,
        "sample_notice": (
            f"This document contains SAMPLE DATA. {assembled.sample_finding_count} of the findings below "
            f"are seeded demonstration data, not observations of a real environment. Individually marked SAMPLE."
        )
        if assembled.contains_sample_data
        else "",
        "truncated_count": assembled.truncated_count,
        "total_matched": assembled.total_matched,
        "truncation_notice": (
            f"{assembled.total_matched} findings matched this report's scope and "
            f"{assembled.truncated_count} could not be included because the scope limit "
            f"({assembled.total_matched - assembled.truncated_count} findings) was reached. "
            f"Findings are included most-severe first, so the omitted findings are the least severe. "
            f"Narrow the scope or raise the limit for a complete listing."
        )
        if assembled.is_truncated
        else "",
        "exclusion_notice": _exclusion_notice(assembled),
        # ── Scan coverage: is this report EMPTY, or is it CLEAN? ──
        # ``has_scan_coverage`` is the ONLY thing that earns the document's
        # "no findings were surfaced" sentence. Without it a never-scanned
        # workspace rendered byte-identically to a thoroughly-scanned clean one.
        "has_scan_coverage": assembled.has_scan_coverage,
        "coverage_notice": _coverage_notice(assembled),
        "untriaged_count": assembled.untriaged_count,
        "untriaged_notice": (
            f"{assembled.untriaged_count} of the findings listed have not been triaged: they were never "
            f"picked up onto the response board and have no assigned owner."
        )
        if assembled.untriaged_count
        else "",
        "highest_band": (assembled.histogram.highest_band or "none").capitalize(),
        "histogram": histogram,
        "matrix": matrix,
        "technical_findings": technical,
        "severity_ratings": severity_ratings,
    }


def _coverage_notice(assembled: AssembledReport) -> str:
    """State whether anything actually scanned — and what did not finish.

    Rendered whenever the answer is anything other than "everything completed":
    no coverage at all, a failed run, or a run still in flight. A clean report
    also states its coverage, because "4 scans completed" is what makes "no
    findings were surfaced" a claim rather than an assumption.
    """
    coverage = assembled.scan_coverage
    if coverage is None:
        return (
            "Scan coverage for this scope was not recorded, so this report cannot state whether any "
            "scan ran over it. Do not read the finding count below as a clean result."
        )

    parts: list[str] = []
    if not coverage.has_coverage:
        parts.append(
            "No completed scan covers this scope for the period reported. This report is empty "
            "because nothing was scanned, not because nothing was found — it is not a clean result."
        )
    else:
        when = (
            f", most recently on {coverage.last_completed_at:%d %B %Y}"
            if coverage.last_completed_at is not None
            else ""
        )
        parts.append(f"{coverage.completed_runs} scans completed over this scope during the period covered{when}.")
    if coverage.failed_runs:
        parts.append(
            f"{coverage.failed_runs} scans failed during the period, so this assessment is incomplete: "
            f"anything those scans would have surfaced is absent from this document."
        )
    if coverage.running_runs:
        parts.append(
            f"{coverage.running_runs} scans were still running when this report was assembled; their "
            f"findings are not included."
        )
    if len(parts) == 1 and coverage.has_coverage:
        # A fully-covered, fully-completed report: the coverage line is a plain
        # statement of fact, not a caveat.
        return parts[0]
    return " ".join(parts)


def _exclusion_notice(assembled: AssembledReport) -> str:
    """State what the report's inclusion policy left out, and why."""
    parts: list[str] = []
    if assembled.excluded_resolved:
        parts.append(
            f"{assembled.excluded_resolved} finding{'s were' if assembled.excluded_resolved != 1 else ' was'} "
            f"resolved during the period covered and {'are' if assembled.excluded_resolved != 1 else 'is'} "
            f"not listed as open"
        )
    if assembled.excluded_suppressed:
        parts.append(
            f"{assembled.excluded_suppressed} finding{'s are' if assembled.excluded_suppressed != 1 else ' is'} "
            f"suppressed as accepted risk or a false positive and "
            f"{'are' if assembled.excluded_suppressed != 1 else 'is'} not listed"
        )
    if assembled.excluded_sample:
        parts.append(f"{assembled.excluded_sample} sample findings were excluded")
    if not parts:
        return ""
    return "In addition to the findings listed: " + "; ".join(parts) + "."


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]
