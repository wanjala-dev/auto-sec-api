"""Use case: archive a suppressed finding's board card(s).

Framework-free orchestration — delegates the tombstone write + provenance
stamp + recycle-bin entry to the injected port. Exists so the project context
owns the card-archival transition and other contexts (the agents board handler
reacting to ``FindingResolved``, the suppressed-cards backfill command) reach
it through this application surface instead of writing the Task — the same
shape as ``ResolveFindingTaskUseCase``.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.project.application.ports.archive_finding_cards_port import (
    ArchiveFindingCardsCommand,
    ArchiveFindingCardsPort,
    ArchiveFindingCardsResult,
)


@dataclass
class ArchiveFindingCardsUseCase:
    port: ArchiveFindingCardsPort

    def execute(self, *, command: ArchiveFindingCardsCommand) -> ArchiveFindingCardsResult:
        return self.port.archive_finding_cards(command=command)
