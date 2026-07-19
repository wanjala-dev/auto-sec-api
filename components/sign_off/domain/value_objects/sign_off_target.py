"""Who/what the artifact is headed for — feeds risk escalation.

A wrong figure emailed to yourself is embarrassing; the same figure sent to a
funder is a credibility (and sometimes legal) problem. Audience + stakes
therefore escalate the content-derived risk band.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Audience(str, Enum):
    INTERNAL_SELF = "internal_self"  # emailed back to the actor who triggered it
    INTERNAL_TEAM = "internal_team"  # workspace members
    EXTERNAL = "external"  # donors, funders, recipients, subscribers, the public


@dataclass(frozen=True)
class SignOffTarget:
    """The destination + stakes of an artifact awaiting sign-off."""

    audience: Audience
    # high_stakes marks artifacts where an error is costly regardless of audience
    # — funder/grant submissions, financial/legal filings, anything irreversible.
    high_stakes: bool = False

    @property
    def escalates(self) -> bool:
        """External delivery or high stakes bump the content band one level."""
        return self.high_stakes or self.audience == Audience.EXTERNAL
