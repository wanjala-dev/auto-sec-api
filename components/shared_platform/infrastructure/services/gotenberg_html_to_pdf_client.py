from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_GOTENBERG_URL = "http://gotenberg:3000"
DEFAULT_TIMEOUT_SECONDS = 30
HTML_FILENAME = "index.html"  # Gotenberg requires the main file be named index.html


@dataclass(frozen=True)
class GotenbergPageOptions:
    """Page-size + margin controls passed as form data to Gotenberg.

    Defaults match a letter-sized page with 0.5–0.6 inch margins — good
    for dashboards and receipts. Override per-document when a different
    paper size or bleed is required.
    """

    paper_width: str = "8.5"
    paper_height: str = "11"
    margin_top: str = "0.55"
    margin_bottom: str = "0.5"
    margin_left: str = "0.6"
    margin_right: str = "0.6"
    print_background: str = "true"


class GotenbergRenderError(RuntimeError):
    """Raised when Gotenberg returns a non-success response.

    Callers catch this and either propagate to the user (sync paths) or
    let the Celery task retry with backoff (async paths). We never swap
    a failure for empty bytes — that would silently ship broken PDFs.
    """


class GotenbergHtmlToPdfClient:
    """Thin HTTP client for Gotenberg's Chromium HTML route.

    Shared across every bounded context that needs HTML → PDF — financial
    reports, receipts, grant summaries, sponsor statements, etc. The
    domain-specific rendering (Jinja template, data shaping) stays in
    each context; this client only cares about the transport.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or getattr(settings, "GOTENBERG_URL", None)
            or DEFAULT_GOTENBERG_URL
        ).rstrip("/")
        self._timeout = int(
            timeout_seconds
            or getattr(settings, "GOTENBERG_TIMEOUT_SECONDS", None)
            or DEFAULT_TIMEOUT_SECONDS
        )

    def render(
        self,
        *,
        html: str,
        log_context: dict[str, object] | None = None,
        page_options: GotenbergPageOptions | None = None,
    ) -> bytes:
        url = f"{self._base_url}/forms/chromium/convert/html"
        opts = page_options or GotenbergPageOptions()
        files = {"files": (HTML_FILENAME, html.encode("utf-8"), "text/html")}
        data = {
            "paperWidth": opts.paper_width,
            "paperHeight": opts.paper_height,
            "marginTop": opts.margin_top,
            "marginBottom": opts.margin_bottom,
            "marginLeft": opts.margin_left,
            "marginRight": opts.margin_right,
            "printBackground": opts.print_background,
        }
        ctx = dict(log_context or {})
        logger.info("gotenberg.render start url=%s %s", url, _fmt_ctx(ctx))
        try:
            response = requests.post(
                url, files=files, data=data, timeout=self._timeout
            )
        except requests.RequestException as exc:
            logger.exception(
                "gotenberg.render transport_error url=%s %s", url, _fmt_ctx(ctx)
            )
            raise GotenbergRenderError(
                f"Gotenberg transport error: {exc}"
            ) from exc

        if response.status_code != 200:
            logger.warning(
                "gotenberg.render non_200 status=%s body=%s %s",
                response.status_code,
                response.text[:500],
                _fmt_ctx(ctx),
            )
            raise GotenbergRenderError(
                f"Gotenberg returned HTTP {response.status_code}"
            )

        body = response.content
        logger.info("gotenberg.render done bytes=%s %s", len(body), _fmt_ctx(ctx))
        return body


def _fmt_ctx(ctx: dict[str, object]) -> str:
    if not ctx:
        return ""
    return " ".join(f"{k}={v}" for k, v in ctx.items())
