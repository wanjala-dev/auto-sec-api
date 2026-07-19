"""Reviewer receipts — the verification signal handed to the human.

This is the anti-rubber-stamp payload: instead of "here's a draft, approve it",
the reviewer sees which figures were checked against the live ledger, which
claims trace to which source record, and which spans tripped the voice lint.
Surfacing this is what makes the human's review *meaningful* (the research
finding) and is the part of the moat no competitor ships.

Fed by the existing faithfulness verifier (SEE-171) and the voice lint; the
kernel only defines the normalized shape so every artifact type reports the
same receipts to the same queue UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FigureCheck:
    """A number/date the draft asserts, checked against source data.

    - verified: stated value matched a source value.
    - contradicted: source value was found AND differs from the stated value
      (the worst case — the draft says $40k, the ledger says $32k).
    - unverifiable: no source value could be found to confirm or deny.
    """

    claim_text: str  # e.g. "$40,000 raised in Q3"
    stated_value: str  # e.g. "40000"
    source_value: str | None = None  # e.g. "32000" from the ledger, or None
    verified: bool = False
    source_ref: str | None = None  # where the source value came from

    @property
    def contradicted(self) -> bool:
        return self.source_value is not None and not self.verified

    @property
    def unverifiable(self) -> bool:
        return self.source_value is None and not self.verified


@dataclass(frozen=True)
class ClaimProvenance:
    """A factual claim in the draft and the record (if any) that grounds it."""

    claim_text: str
    source_record_ref: str | None = None  # which workspace record supports it
    grounded: bool = False


@dataclass(frozen=True)
class VoiceFlag:
    """A span the voice lint flagged (negative framing, jargon, reading level)."""

    span: str
    issue: str


@dataclass(frozen=True)
class ReviewerReceipts:
    """The full verification packet for one artifact awaiting sign-off."""

    figure_checks: tuple[FigureCheck, ...] = field(default_factory=tuple)
    claim_provenance: tuple[ClaimProvenance, ...] = field(default_factory=tuple)
    voice_flags: tuple[VoiceFlag, ...] = field(default_factory=tuple)

    @property
    def contradicted_figures(self) -> tuple[FigureCheck, ...]:
        return tuple(f for f in self.figure_checks if f.contradicted)

    @property
    def unverifiable_figures(self) -> tuple[FigureCheck, ...]:
        return tuple(f for f in self.figure_checks if f.unverifiable)

    @property
    def ungrounded_claims(self) -> tuple[ClaimProvenance, ...]:
        return tuple(c for c in self.claim_provenance if not c.grounded)

    @property
    def has_flags(self) -> bool:
        """Any unverifiable figure, ungrounded claim, or voice flag (amber-grade)."""
        return bool(self.unverifiable_figures or self.ungrounded_claims or self.voice_flags)

    @property
    def has_contradictions(self) -> bool:
        """Any figure that the source data actively contradicts (red-grade)."""
        return bool(self.contradicted_figures)

    @property
    def is_clean(self) -> bool:
        return not self.has_flags and not self.has_contradictions
