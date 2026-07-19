"""Resolve the default DESIGN layout for a blank draft of a given kind.

Task #19 — "AI layouts for blank designed drafts": when a user generates
into a draft that has no block layout (they started blank instead of
composing from a design template), the ask-ai path applies the kind's
default design so the result is a designed document, not a wall of text.

The design SSOT stays the template kernel: this use case never invents a
block tree — it picks an existing design template for the kind (the
workspace's own customisation beats the seeded ones), resolves its
workspace placeholders, and hands the layout to the SAME per-field
completion pipeline (grounding + faithfulness + verbatim guard) that
template-composed drafts already ride. Kinds with no design template
(letters — they render on the letterhead) resolve to None and keep the
classic prose path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.content.application.ports.writing_template_reader_port import (
    WritingTemplateReaderPort,
)
from components.content.application.services.layout_placeholder_service import (
    resolve_layout_placeholders,
)

logger = logging.getLogger(__name__)


def _layout_of(template: Any) -> dict | None:
    layout = (getattr(template, "metadata", None) or {}).get("layout")
    if isinstance(layout, dict) and layout.get("blocks"):
        return layout
    return None


@dataclass
class ResolveDefaultDesignLayoutUseCase:
    writing_templates: WritingTemplateReaderPort
    placeholder_resolver: Any = field(default=None)

    def execute(self, *, workspace_id: UUID, kind: str) -> dict | None:
        try:
            templates = self.writing_templates.list_available(workspace_id=workspace_id, kind=kind)
        except Exception:
            logger.exception(
                "default_design_layout.list_failed workspace_id=%s kind=%s",
                workspace_id,
                kind,
            )
            return None

        candidates = [t for t in templates if _layout_of(t)]
        if not candidates:
            return None
        # A workspace-authored design beats the seeded ones; within each
        # group list_available orders newest-first.
        own = [t for t in candidates if getattr(t, "workspace_id", None)]
        chosen = (own or candidates)[0]
        layout = _layout_of(chosen)

        # Donate-URL + workspace placeholder resolution — the same pass a
        # template-composed draft gets in CreateWritingDraftUseCase. Both
        # halves are decoration: any failure returns the raw layout (the
        # editor highlights unresolved tokens).
        donate_url = ""
        try:
            from components.content.application.use_cases.generate_newsletter_use_case import (
                _workspace_donate_url,
            )

            donate_url = _workspace_donate_url(workspace_id)
        except Exception:
            donate_url = ""
        try:
            return resolve_layout_placeholders(
                layout,
                self.placeholder_resolver,
                workspace_id,
                donate_url=donate_url,
            )
        except Exception:
            logger.exception(
                "default_design_layout.resolve_failed workspace_id=%s kind=%s template=%s",
                workspace_id,
                kind,
                getattr(chosen, "id", None),
            )
            return layout
