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
    from components.shared_platform.infrastructure.services.pdf_brand_assets import (
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
        "highest_band": (assembled.histogram.highest_band or "none").capitalize(),
        "histogram": histogram,
        "matrix": matrix,
        "technical_findings": technical,
        "severity_ratings": severity_ratings,
    }


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]
