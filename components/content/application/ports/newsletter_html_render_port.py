"""Port: render a newsletter block tree to email-safe HTML.

The newsletter ``content_payload['layout']`` block tree (built by
``newsletter_block_composer.compose``) is the canonical source of truth for
a *designed* newsletter. The frontend renders it as React/Tailwind blocks for
the visual editor — but the **sent email** and the **PDF** need server-rendered
HTML, and the in-app *preview* must show that same HTML so what the user sees is
exactly what subscribers receive (no two-renderer drift).

This port is that single rendering seam. One adapter implements it; send, PDF
export, and the preview endpoint all call it, so they can never disagree.

Why a port (per ``/templates`` skill §3a.D — "swap the adapter, not the app
code"): rendering is infrastructure. Today's adapter builds email-safe,
table-based, inline-styled HTML in pure Python (no new deps, unit-testable
without Django). A future ``MjmlNewsletterHtmlRenderAdapter`` (responsive-email
transpile) or a Django-template adapter is a drop-in replacement — no caller
changes. When the kernel's generic ``TemplateRenderPort`` lands (skill §3a.D /
the template-kernel consolidation), this becomes one of its registered backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NewsletterHtmlRenderPort(ABC):
    """Render a newsletter layout block tree into a complete HTML email body."""

    @abstractmethod
    def render(
        self,
        *,
        layout: dict[str, Any] | None,
        fallback_html: str = "",
        context: dict[str, Any] | None = None,
    ) -> str:
        """Return a full, email-safe HTML document for the newsletter.

        ``layout`` is the ``{"version": int, "blocks": [...]}`` envelope from
        ``Newsletter.content_payload['layout']``. When it is missing or has no
        renderable blocks (true legacy newsletters drafted before the block
        composer existed), the adapter wraps ``fallback_html`` (the row's
        ``content_html`` prose) in the same envelope chrome so even legacy rows
        render coherently.

        ``context`` carries optional presentation hints the layout itself does
        not encode — e.g. ``{"preheader": str, "title": str}``. Per-recipient
        merge tokens (``{{subscriber_first_name}}``, ``{{unsubscribe_url}}``)
        are NOT resolved here; they are intentionally left intact for the
        dispatch adapter to substitute per recipient.

        The returned HTML is a standalone document (``<!DOCTYPE html>`` …) safe
        to drop straight into an ``EmailMultiAlternatives`` HTML alternative, a
        Gotenberg PDF render, or a preview ``<iframe srcdoc>``.
        """
        raise NotImplementedError
