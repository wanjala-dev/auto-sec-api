"""ResponseOutcome — what a CloudResponsePort call returns.

Uniform across execute + rollback, real + dry-run, so the use cases branch on
one shape. ``dry_run`` records whether AWS was actually mutated or only
permission-checked (boto3 ``DryRun`` → ``DryRunOperation`` when permitted); the
adapter maps that native behaviour into ``performed`` / ``would_succeed``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResponseOutcome:
    #: The mutation actually ran against AWS (dry_run False and it succeeded).
    performed: bool
    #: This was a dry-run — no state changed; ``would_succeed`` says whether it
    #: *would* have (permissions present) per AWS's DryRun probe.
    dry_run: bool
    would_succeed: bool = False
    #: Raw provider detail (RevokedSecurityGroupRules, error code) for the ledger.
    detail: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Cleared: either it really ran, or a dry-run confirmed it would."""
        return self.error is None and (self.performed or (self.dry_run and self.would_succeed))
