"""The workspace-brand fields a newsletter draft needs to lay itself out.

``GenerateNewsletterUseCase`` needs a handful of workspace fields — the org
name (for the grounded fallback prose + footer), contact email, mission (footer
tagline), and cover/logo photo URLs (hero + spotlight imagery). The workspace
is another bounded context, so the use case must NOT read its ORM directly:
the content-owned ``WorkspaceProfilePort`` returns this frozen value object so
the fields flow across the layer boundary without leaking the ``Workspace``
model into the application layer (C3 — cross-context reads are read-only, and
travel as domain types).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceProfile:
    """Read-only projection of the workspace fields a newsletter draft uses.

    Every field defaults to empty — a missing workspace or read error degrades
    to a blank profile (the composer drops blocks it can't populate, the
    grounded summary falls back to a generic org label, and the hero falls back
    to a curated stock photo).
    """

    name: str = ""
    contact_email: str = ""
    mission: str = ""
    cover_photo_url: str = ""
    photo_url: str = ""
