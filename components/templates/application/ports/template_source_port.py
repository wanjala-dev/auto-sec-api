"""The contract a template kind implements to appear in the unified gallery.

A source knows how to enumerate one kind's templates for a workspace (its own
workspace-owned templates PLUS the system/global ones) as normalized
``TemplateSummary`` rows. The kernel registry holds one source per kind; the
gallery controller fans out across the registered sources.

This is the ONLY thing a new kind must provide to be listable — keeping the
payload, render, and apply logic in the owning context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from components.templates.domain.entities.template_summary_entity import TemplateSummary


class TemplateSourcePort(ABC):
    @abstractmethod
    def kind(self) -> str:
        """The canonical kind id this source serves (e.g. 'workflow_template')."""

    @abstractmethod
    def list_templates(self, workspace_id: Optional[str]) -> List[TemplateSummary]:
        """Return system templates + the workspace's own templates for this kind."""
