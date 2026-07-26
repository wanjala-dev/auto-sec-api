"""Resource DTO for the on-demand container-scan endpoint response."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerScanResource:
    task_id: str
    image: str
    source: str

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "image": self.image, "source": self.source}
