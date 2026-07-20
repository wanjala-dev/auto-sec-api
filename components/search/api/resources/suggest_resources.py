"""Output DTO for GET /search/suggest/.

The frontend search service reads ``response.data.sections`` and renders
each section's items generically (``title`` / ``subtitle`` / ``url``), so
the resource wraps the service's section map under a ``sections`` key.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SuggestSectionsResource:
    """Section map ready for JSON rendering."""

    sections: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"sections": self.sections}
