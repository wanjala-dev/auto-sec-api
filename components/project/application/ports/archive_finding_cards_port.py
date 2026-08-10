"""Port: archive a suppressed finding's board card(s) into the recycle bin.

When a finding is SUPPRESSED (accepted risk / false positive / demo noise), its
board card is stale intake noise — Henry's ruling (2026-08-09) is that it
auto-archives off the Suggested/intake lane. The archive is the recycle-bin
tombstone (``status=ARCHIVED`` + a ``RecycleBinEntry``), NEVER a delete: the
card drops off every board read but stays restorable from the board's RECYCLE
BIN tray, and the finding row itself (the SSOT record) is untouched.

The project context owns the board ``Task``, so this is the sanctioned surface
other contexts (the agents board handler reacting to ``FindingResolved``, the
backfill command) route through — mirroring ``ResolveFindingTaskPort``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ArchiveFindingCardsCommand:
    workspace_id: UUID
    # The SSOT finding UUID (str) the card was stamped with at birth
    # (``metadata.payload.finding_id``) — the primary lookup key.
    finding_id: str
    # The finding fingerprint (= the card's ``metadata.payload.lookup_key``) —
    # the fallback lookup for cards persisted before finding_id stamping.
    fingerprint: str
    # Coarse cause token carried on the FindingResolved event ("suppressed").
    reason: str
    # The operator's risk-acceptance "why" (Finding.status_reason), "" if none.
    detail: str = ""
    # The user the recycle-bin entry + provenance comment are attributed to
    # (the workspace's AI teammate user — resolved by the caller).
    archived_by: UUID | None = None
    # Human-readable actor label for the provenance trail.
    actor_label: str = "system:finding_suppressed"


@dataclass(frozen=True)
class ArchiveFindingCardsResult:
    # Cards archived by THIS call (str task ids).
    archived_task_ids: tuple[str, ...]
    # Live cards found but already in the bin when we reached them (race).
    already_archived: int

    @property
    def archived_count(self) -> int:
        return len(self.archived_task_ids)


class ArchiveFindingCardsPort(abc.ABC):
    """Secondary port for the suppressed-finding card archive write."""

    @abc.abstractmethod
    def archive_finding_cards(self, *, command: ArchiveFindingCardsCommand) -> ArchiveFindingCardsResult:
        """Archive every live board card of the finding into the recycle bin.

        Idempotent: already-archived cards are skipped (a re-suppress or a
        replayed event archives nothing twice). Each archived card gets a
        provenance event + a card comment naming why it was archived (the
        AI-actions-on-board principle), then is trashed through the
        recycle_bin application service — the same path the HUD's card
        delete uses, so the RECYCLE BIN tray restore works unchanged.
        """
        ...
