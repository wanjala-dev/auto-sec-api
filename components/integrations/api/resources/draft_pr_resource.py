"""Resource DTO: draft-PR result payload."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DraftPrResource:
    url: str
    repo: str
    branch: str
    created: bool
    #: "verified" | "unverified" | "" — the confidence LABEL stamped on the PR
    #: (title prefix + body section). An unverified PR still opens; the label,
    #: not a withheld artifact, carries the doubt.
    verification: str = ""
    verification_gap: str = ""

    @classmethod
    def from_result(cls, result) -> DraftPrResource:
        return cls(
            url=result.url,
            repo=result.repo,
            branch=result.branch,
            created=result.created,
            verification=getattr(result, "verification", "") or "",
            verification_gap=getattr(result, "verification_gap", "") or "",
        )

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "repo": self.repo,
            "branch": self.branch,
            "created": self.created,
            "verification": self.verification,
            "verification_gap": self.verification_gap,
        }
