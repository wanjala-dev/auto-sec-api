"""Map an assembled report + workspace brand into the template render context.

The cover brand is the WORKSPACE ORG identity (name + logo + colours), resolved
via ``resolve_brand_colors`` + the workspace ``photo_url`` (falling back to the
default Octopus mark). The assessed target/scope is data the operator supplied —
never confused with the vendor identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from components.report.domain.entities.assembled_report import AssembledReport
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
        "finding_total": assembled.histogram.total,
        "highest_band": (assembled.histogram.highest_band or "none").capitalize(),
        "histogram": histogram,
        "matrix": matrix,
        "technical_findings": technical,
        "severity_ratings": severity_ratings,
    }


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]
