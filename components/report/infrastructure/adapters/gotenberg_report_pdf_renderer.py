"""Gotenberg-backed :class:`ReportPdfRendererPort`.

Wraps the shared ``GotenbergHtmlToPdfClient`` — the template already sets its own
``@page`` size + margins to zero, so we pass a full-bleed page and let the CSS
own the layout.
"""

from __future__ import annotations

from components.report.application.ports.report_pdf_renderer_port import ReportPdfRendererPort
from components.shared_platform.infrastructure.services.gotenberg_html_to_pdf_client import (
    GotenbergHtmlToPdfClient,
    GotenbergPageOptions,
)


class GotenbergReportPdfRenderer(ReportPdfRendererPort):
    def __init__(self, client: GotenbergHtmlToPdfClient | None = None) -> None:
        self._client = client or GotenbergHtmlToPdfClient()

    def render(self, *, html: str, log_context: dict | None = None) -> bytes:
        # The template controls page size via its own @page/CSS (margin 0), so
        # we render letter-size with zero margins and print backgrounds.
        options = GotenbergPageOptions(
            paper_width="8.5",
            paper_height="11",
            margin_top="0",
            margin_bottom="0",
            margin_left="0",
            margin_right="0",
            print_background="true",
        )
        return self._client.render(html=html, log_context=log_context, page_options=options)
