"""Published seam for the shared Gotenberg HTML->PDF client.

PDF rendering via Gotenberg lives in shared_platform infrastructure. Other
contexts that render PDFs (content writing, report generation) reach the client,
its page options, and its render error through this application-layer re-export
instead of importing ``shared_platform.infrastructure.services
.gotenberg_html_to_pdf_client`` directly (ADR 0004 infra-boundary series).
"""

from __future__ import annotations

from components.shared_platform.infrastructure.services.gotenberg_html_to_pdf_client import (
    GotenbergHtmlToPdfClient,
    GotenbergPageOptions,
    GotenbergRenderError,
)

__all__ = ["GotenbergHtmlToPdfClient", "GotenbergPageOptions", "GotenbergRenderError"]
