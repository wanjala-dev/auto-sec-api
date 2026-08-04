"""Command + result for the operator-driven finding lifecycle transition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# The lifecycle actions an operator can take on a finding from the HUD. Each maps to a
# terminal/open transition on the FindingEntity — no hard delete (the record is retained
# for audit and a re-observation reopens a terminal finding).
RESOLVE = "resolve"
SUPPRESS = "suppress"
REOPEN = "reopen"
VALID_ACTIONS: frozenset[str] = frozenset({RESOLVE, SUPPRESS, REOPEN})


@dataclass(frozen=True)
class ChangeFindingStatusCommand:
    workspace_id: UUID
    finding_id: UUID
    action: str
    at: datetime
    actor_id: str | None = None


@dataclass(frozen=True)
class ChangeFindingStatusResult:
    finding_id: UUID
    status: str
    changed: bool
