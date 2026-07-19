"""Template kernel domain errors.

Sub-classes of the shared exception taxonomy so controllers and middleware can
catch at the taxonomy level for uniform HTTP mapping while still surfacing
template-specific semantics.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import DomainError, NotFoundError


class TemplateError(DomainError):
    """Base error for template-kernel invariant violations."""


class UnknownTemplateKind(TemplateError, NotFoundError):
    """A kind id was requested that no source is registered for (→ 404)."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"Unknown template kind: {kind!r}")
        self.kind = kind
