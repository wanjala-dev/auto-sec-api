from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class Result:
    """Shared result envelope for application handlers."""

    ok: bool
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
