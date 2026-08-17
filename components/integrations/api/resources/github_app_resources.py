"""Resource DTOs for the GitHub App install flow (ADR 0010 D6 / Phase B)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubAppInstallResource:
    """The install hand-off: the FE opens ``install_url`` in a new tab. The URL
    carries the signed state; nothing else crosses this response."""

    install_url: str

    def to_dict(self) -> dict:
        return {"install_url": self.install_url}
