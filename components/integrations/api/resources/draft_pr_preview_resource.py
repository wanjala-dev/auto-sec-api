"""Resource DTO: draft-PR PREVIEW payload (ADR 0012 P6 preview-before-commit)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DraftPrPreviewResource:
    path: str
    diff: str
    change_summary: str
    grounding: tuple[dict, ...]
    repo: str
    already_opened: bool
    pr_url: str

    @classmethod
    def from_result(cls, result) -> DraftPrPreviewResource:
        return cls(
            path=result.path,
            diff=result.diff,
            change_summary=result.change_summary,
            grounding=tuple(result.grounding),
            repo=result.repo,
            already_opened=result.already_opened,
            pr_url=result.pr_url,
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "diff": self.diff,
            "change_summary": self.change_summary,
            "grounding": [dict(g) for g in self.grounding],
            "repo": self.repo,
            "already_opened": self.already_opened,
            "pr_url": self.pr_url,
        }
