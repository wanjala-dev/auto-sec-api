"""Remediation-context domain errors — mapped onto the shared exception taxonomy.

The load-bearing one is :class:`EntryGateNotSatisfiedError` — the entry-gate
refusing to admit a candidate because at least one of the three conditions
(sign-off approved, draft PR applied, finding resolved) does not hold. This is
the security control (ADR 0012 D1): a refusal here is the system *structurally*
declining to teach an unvetted fix, not a recoverable validation nicety.
"""

from __future__ import annotations

from collections.abc import Sequence

from components.shared_kernel.domain.errors import DomainError, NotFoundError, ValidationError


class RemediationError(DomainError):
    """Base for remediation-context domain failures."""


class RemediationEntryNotFoundError(RemediationError, NotFoundError):
    def __init__(self, entry_id: str) -> None:
        super().__init__(f"remediation entry {entry_id} not found")
        self.entry_id = entry_id


class EntryGateNotSatisfiedError(RemediationError, ValidationError):
    """The candidate did not clear the D1 entry-gate — one or more of
    {sign-off approved, PR applied, finding resolved} is missing.

    Carries the specific ``unmet`` reasons so the caller/audit can see exactly
    which condition failed. Raising this is the *point* — corpus membership is
    earned, and an unearned candidate is refused, never quietly admitted.
    """

    def __init__(self, unmet: Sequence[str]) -> None:
        self.unmet = tuple(unmet)
        joined = ", ".join(self.unmet) or "unknown"
        super().__init__(f"remediation entry-gate not satisfied: {joined}")
