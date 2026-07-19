from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DataTransferObject:
    """Simple DTO base for request/response contracts."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
