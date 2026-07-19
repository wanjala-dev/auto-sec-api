"""Request DTO: open a draft PR for a triaged finding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenDraftPrRequest:
    """Input for ``POST /integrations/workspaces/<ws>/findings/<task>/open-draft-pr/``."""

    repo: str | None = None

    @classmethod
    def from_payload(cls, data: dict) -> OpenDraftPrRequest:
        data = data or {}
        repo = str(data.get("repo") or "").strip()
        return cls(repo=repo or None)
