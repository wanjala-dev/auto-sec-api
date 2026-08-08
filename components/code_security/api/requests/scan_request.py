"""Request DTO for the on-demand repo-scan endpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoScanRequest:
    repo: str
    connection_id: str | None = None

    @classmethod
    def from_data(cls, data: dict) -> RepoScanRequest:
        return cls(
            repo=(data.get("repo") or "").strip(),
            connection_id=data.get("connection_id") or None,
        )
