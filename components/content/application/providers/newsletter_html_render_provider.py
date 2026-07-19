"""Composition root for the newsletter HTML render port.

Wires ``NewsletterHtmlRenderPort`` to its concrete adapter so primary adapters
(the controller's detail serialization, the preview surface) obtain the renderer
through the application layer rather than importing infrastructure directly
(architecture-manifesto Rule 10). Swap the adapter here to change the render
backend (e.g. MJML) with no caller change.
"""

from __future__ import annotations

from components.content.application.ports.newsletter_html_render_port import (
    NewsletterHtmlRenderPort,
)


class NewsletterHtmlRenderProvider:
    def renderer(self) -> NewsletterHtmlRenderPort:
        from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
            EmailNewsletterHtmlRenderAdapter,
        )

        return EmailNewsletterHtmlRenderAdapter()


def get_newsletter_html_render_provider() -> NewsletterHtmlRenderProvider:
    return NewsletterHtmlRenderProvider()
