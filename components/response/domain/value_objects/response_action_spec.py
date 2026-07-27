"""ResponseActionSpec — the fully-specified mutation, and its exact inverse.

A response action is only *reversible* if we can reconstruct the undo precisely.
``inverse()`` flips the kind (revoke ↔ authorize) while keeping the account,
region, group and rule identical — so restoring a revoked rule re-creates the
same rule, and undoing a mistaken authorize removes exactly what was added. The
spec is what the human approver sees, what the adapter executes, and what the
ledger stores; there is one description of the change, not three.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule


@dataclass(frozen=True)
class ResponseActionSpec:
    kind: ResponseActionKind
    account_id: str
    region: str
    group_id: str
    rule: SecurityGroupRule

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("ResponseActionSpec.account_id is required")
        if not self.region:
            raise ValueError("ResponseActionSpec.region is required")
        if not self.group_id:
            raise ValueError("ResponseActionSpec.group_id is required")

    def inverse(self) -> ResponseActionSpec:
        """The action that undoes this one — same target, opposite verb."""
        return ResponseActionSpec(
            kind=self.kind.inverse_kind,
            account_id=self.account_id,
            region=self.region,
            group_id=self.group_id,
            rule=self.rule,
        )

    def human_summary(self) -> str:
        verb = "Revoke" if self.kind == ResponseActionKind.REVOKE_SG_INGRESS else "Re-authorize"
        return f"{verb} ingress {self.rule.human_label()} on {self.group_id} ({self.account_id}/{self.region})"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "account_id": self.account_id,
            "region": self.region,
            "group_id": self.group_id,
            "rule": self.rule.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResponseActionSpec:
        return cls(
            kind=ResponseActionKind(data["kind"]),
            account_id=str(data["account_id"]),
            region=str(data["region"]),
            group_id=str(data["group_id"]),
            rule=SecurityGroupRule.from_dict(data["rule"]),
        )
