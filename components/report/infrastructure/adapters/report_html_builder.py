"""Render the branded report HTML from the assembled data.

Thin adapter: builds the template context (via the mapper) and renders the
kind's Django template. No business logic — the assembler already produced the
data, the mapper shaped it, this only calls ``render_to_string``.
"""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string

from components.report.domain.entities.assembled_report import AssembledReport
from components.report.domain.report_kind import get_report_kind
from components.report.mappers.rest.report_context_mapper import build_render_context


def build_report_html(
    *,
    assembled: AssembledReport,
    kind: str,
    title: str,
    scope: dict[str, Any],
    workspace_id: str,
    workspace_name: str,
    workspace_logo_url: str,
) -> str:
    spec = get_report_kind(kind)
    context = build_render_context(
        assembled=assembled,
        kind=kind,
        title=title,
        scope=scope,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        workspace_logo_url=workspace_logo_url,
    )
    return render_to_string(spec.template_name, context)
