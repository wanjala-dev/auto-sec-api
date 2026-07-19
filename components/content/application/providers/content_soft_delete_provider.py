"""Composition root for the content context's recycle-bin adapters
(task #29). The recycle-bin provider imports THIS front door — never
content's infrastructure directly (Rule 3)."""

from __future__ import annotations


def get_content_soft_delete_adapters():
    from components.content.infrastructure.adapters.content_soft_delete_adapters import (
        NewsletterSoftDeleteAdapter,
        WritingDraftSoftDeleteAdapter,
    )

    return [WritingDraftSoftDeleteAdapter(), NewsletterSoftDeleteAdapter()]
