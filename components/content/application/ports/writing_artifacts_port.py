"""Cross-context port: surfaces writing artifacts (drafts, newsletters, blogs)
to other bounded contexts (specifically ``shared_platform``'s unified-documents
controller) without leaking ORM models across context boundaries.

This is the only sanctioned surface for cross-context consumers to list
writing artifacts. Direct imports of Newsletter / WritingDraft / News
models from outside the content context violate the Explicit Architecture
rule and the ``test_cross_context_import_rules`` architecture test.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True)
class WritingArtifactSummary:
    """Shape returned for cross-context consumers (e.g., unified-docs feed).

    ``kind`` is one of ``WritingArtifactKind`` values
    (newsletter / draft / blog). ``status`` is the source artifact's
    status string. ``source_type`` matches the frontend Documents-tab
    source enum (e.g., ``'newsletter'``, ``'writing_draft'``, ``'blog'``)
    so the existing card grid can render it without bespoke handling.
    """

    id: UUID | int
    workspace_id: UUID
    kind: str
    source_type: str
    title: str
    preview: str
    status: str
    author_id: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    pdf_url: str | None = None
    metadata: dict = field(default_factory=dict)


class WritingArtifactsPort(Protocol):
    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WritingArtifactSummary]:
        """Return a unified list of writing artifacts for the workspace,
        sorted by ``updated_at DESC`` across the union. ``kinds`` filters
        to a subset of ``WritingArtifactKind`` values; None returns all."""
        ...
