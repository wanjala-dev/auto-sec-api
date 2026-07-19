"""Resource DTO: draft-PR result payload."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DraftPrResource:
    url: str
    repo: str
    branch: str
    created: bool

    @classmethod
    def from_result(cls, result) -> DraftPrResource:
        return cls(url=result.url, repo=result.repo, branch=result.branch, created=result.created)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "repo": self.repo,
            "branch": self.branch,
            "created": self.created,
        }
