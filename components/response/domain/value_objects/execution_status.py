"""ExecutionStatus — the response-action lifecycle, and its legal transitions.

    PROPOSED ──approve──▶ EXECUTED ──rollback──▶ ROLLED_BACK
       │                    │
       ├──reject──▶ REJECTED └──(execute failed)──▶ FAILED

The lifecycle is the human-in-the-loop gate: an action is born PROPOSED (no
external effect yet) and only leaves that state by an explicit human decision.
Only an EXECUTED action can be rolled back; only a PROPOSED one can be approved
or rejected. ``can_*`` encode that so a use case never has to re-derive it.
"""

from __future__ import annotations

from enum import Enum


class ExecutionStatus(str, Enum):
    PROPOSED = "proposed"  # recorded, awaiting a human decision — no cloud change yet
    EXECUTED = "executed"  # the mutation ran against the cloud (or a dry-run of it)
    FAILED = "failed"  # approved + attempted, but the cloud call errored
    REJECTED = "rejected"  # a human declined the proposal
    ROLLED_BACK = "rolled_back"  # the inverse ran — the change has been undone

    @property
    def can_approve(self) -> bool:
        return self == ExecutionStatus.PROPOSED

    @property
    def can_reject(self) -> bool:
        return self == ExecutionStatus.PROPOSED

    @property
    def can_rollback(self) -> bool:
        return self == ExecutionStatus.EXECUTED

    @property
    def is_terminal(self) -> bool:
        return self in (ExecutionStatus.REJECTED, ExecutionStatus.ROLLED_BACK)
