"""Composition root for content sign-off (Phase 5 read-side retrofit).

Wires the content context's read-side ``SignOffPort`` adapters (newsletter +
writing draft) into the kernel registry. Keeping the concrete-adapter imports
here — not in ``api/`` or the persistence ``apps.py`` inline — honours the
architecture rule that primary adapters depend on providers, and centralises
the "which adapter implements which artifact_type" policy decision in the
application layer where it belongs.

This provider is read-side only: it exposes no ``build_service`` /
``set_state`` path. Newsletter + writing-draft transitions stay owned by their
existing Send / Publish use cases; the kernel only *reads* their state.
"""

from __future__ import annotations

from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)


class ContentSignOffProvider:
    def build_newsletter_adapter(self):
        from components.content.infrastructure.adapters.newsletter_sign_off_adapter import (
            NewsletterSignOffAdapter,
        )

        return NewsletterSignOffAdapter()

    def build_writing_draft_adapter(self):
        from components.content.infrastructure.adapters.writing_draft_sign_off_adapter import (
            WritingDraftSignOffAdapter,
        )

        return WritingDraftSignOffAdapter()

    def register_adapters(self) -> None:
        """Register both content adapters with the process-wide kernel registry."""
        registry = get_sign_off_registry()
        registry.register(self.build_newsletter_adapter())
        registry.register(self.build_writing_draft_adapter())


_default = ContentSignOffProvider()


def get_content_sign_off_provider() -> ContentSignOffProvider:
    return _default
