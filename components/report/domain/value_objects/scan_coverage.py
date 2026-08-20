"""Did anything actually LOOK at this scope, and did it finish?

Zero findings is not a result — it is the *absence* of one, and the two read
identically unless the deliverable says which it is. A workspace that was never
connected, a scope filter that matched no pillar, and a period in which every
scan crashed all produce an empty finding set; so does a thorough scan of a
genuinely clean estate. Only the last of those may be reported as "no findings
were surfaced".

Pure domain: no framework, no ORM. The finding port carries it, the assembler
puts it on the report, and the document renders it — because a report is an
evidence artifact that leaves the building, and an absence of data presented as a
clean result is the most damaging claim this product can make.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScanCoverage:
    """Scan-execution facts for one report's scope + period.

    Counted over the report's own scope, so the answer describes THIS report
    rather than the workspace's lifetime.

    ``None`` wherever this is optional means the source cannot answer — a third
    state, distinct from "nothing ran". Silence must never be rendered as a clean
    result (fail-closed, the same rule the entitlement and attestation gates
    follow).
    """

    #: Runs that reached ``completed`` — the only thing that earns a clean claim.
    completed_runs: int = 0
    #: Runs that reached ``failed``. Non-zero means the assessment is INCOMPLETE,
    #: whatever the finding count, and the document must say so.
    failed_runs: int = 0
    #: Runs still ``pending``/``running`` when the report was assembled — their
    #: findings are not in it yet.
    running_runs: int = 0
    #: When the most recent completed run finished, for the coverage statement.
    last_completed_at: datetime | None = None

    @property
    def has_coverage(self) -> bool:
        """True only when a scan actually completed over this scope."""
        return self.completed_runs > 0

    @property
    def is_incomplete(self) -> bool:
        """Something in this period did not finish — the report is partial."""
        return self.failed_runs > 0 or self.running_runs > 0
