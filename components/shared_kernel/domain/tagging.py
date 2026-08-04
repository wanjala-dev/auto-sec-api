"""Shared tagging value object — the cross-context tag read carrier (ADR 0015).

``TagRef`` is the immutable projection other contexts carry when they render or
return a tag (e.g. ``FindingEntity.tags``). It lives in the shared kernel — not in
the ``tagging`` context — because a consuming context's *domain* layer may only
depend on its own domain + the shared kernel (the
``test_domain_does_not_import_other_contexts`` fitness function), and the kernel is
the codified home for cross-context value identities (architecture skill C4 — same
placement as ``AssetUrn``/``Severity``). The ``tagging`` bounded context OWNS the
vocabulary (entity, lifecycle, CRUD, ``TagStorePort``); this is only the read shape
that travels across contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

__all__ = ["TagRef"]


@dataclass(frozen=True)
class TagRef:
    """A reference to a live tag: the identity (``id``), the filter/API handle
    (``slug``), and the display fields (``name``, ``color``).

    Durable references (workflow rule configs, saved views) MUST store ``id`` —
    the slug is a display/API handle that a rename can change (ADR 0015 D5).
    """

    id: UUID
    slug: str
    name: str
    color: str = ""
