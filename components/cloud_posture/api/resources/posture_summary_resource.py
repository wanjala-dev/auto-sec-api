"""Output DTO — the cloud-posture summary rendered to the HUD card."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostureSummaryResource:
    accounts: list
    account_count: int
    totals: dict

    @classmethod
    def from_summary(cls, summary: dict) -> "PostureSummaryResource":
        return cls(
            accounts=summary.get("accounts", []),
            account_count=summary.get("account_count", 0),
            totals=summary.get("totals", {}),
        )

    def to_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "account_count": self.account_count,
            "totals": self.totals,
        }
