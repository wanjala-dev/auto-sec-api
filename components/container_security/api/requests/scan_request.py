"""Request DTO for the on-demand container-scan endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContainerScanRequest:
    image: str
    connection_id: str | None = None
    account_id: str = ""
    allowed_registries: tuple[str, ...] | None = None
    params: dict = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: dict) -> ContainerScanRequest:
        allowed = data.get("allowed_registries") or None
        return cls(
            image=(data.get("image") or "").strip(),
            connection_id=data.get("connection_id"),
            account_id=data.get("account_id", ""),
            allowed_registries=tuple(allowed) if allowed else None,
            params={"allowed_registries": list(allowed)} if allowed else {},
        )
