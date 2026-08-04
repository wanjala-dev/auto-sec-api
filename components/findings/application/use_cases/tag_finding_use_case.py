"""Tag/untag a finding — the write behind the HUD Tag action (ADR 0015 D6).

Framework-free orchestration. The vocabulary is consumed ONLY through the tagging
context's ``TagStorePort`` (auto-create on first use — D4); the join edges are
written through the findings-owned ``FindingTagStorePort`` (D10). Removal of an
edge is a hard delete — the join is an edge, not a record; provenance is the audit
log line, matching how status changes audit.
"""

from __future__ import annotations

import logging

from components.findings.application.commands.tag_finding_command import (
    TagFindingCommand,
    TagFindingResult,
)
from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.ports.finding_tag_store_port import FindingTagStorePort
from components.findings.domain.errors import FindingNotFoundError
from components.tagging.application.ports.tag_store_port import TagStorePort
from components.tagging.domain.constants import MAX_TAGS_PER_FINDING
from components.tagging.domain.errors import TagLimitExceededError

logger = logging.getLogger(__name__)


class TagFindingUseCase:
    def __init__(
        self,
        *,
        finding_store: FindingStorePort,
        tag_store: TagStorePort,
        link_store: FindingTagStorePort,
    ) -> None:
        self._finding_store = finding_store
        self._tag_store = tag_store
        self._link_store = link_store

    def execute(self, command: TagFindingCommand) -> TagFindingResult:
        # 1. Load the finding (404 if absent / other-workspace).
        finding = self._finding_store.find_by_id(command.workspace_id, command.finding_id)
        if finding is None:
            raise FindingNotFoundError(f"Finding {command.finding_id} not found in workspace {command.workspace_id}.")

        # 2. Resolve removals — unknown slugs are no-ops (D6).
        remove_ids: set = set()
        if command.remove:
            remove_ids = set(self._tag_store.resolve_slugs(command.workspace_id, command.remove).values())

        # 3. Resolve additions via get_or_create — auto-create user tags on first
        #    use (D4); ReservedTagError/InvalidTagError/TagLimitExceededError bubble → 400.
        add_ids: list = []
        for raw in command.add:
            tag = self._tag_store.get_or_create(command.workspace_id, raw)
            add_ids.append(tag.id)

        # 4. Enforce the tags-per-finding cap on the prospective set (D3: ≤ 50).
        existing_ids = self._link_store.tag_ids_for_finding(command.workspace_id, command.finding_id)
        prospective = (existing_ids - remove_ids) | set(add_ids)
        if len(prospective) > MAX_TAGS_PER_FINDING:
            raise TagLimitExceededError(f"A finding can carry at most {MAX_TAGS_PER_FINDING} tags.")

        # 5. Write the edges — idempotent adds, hard-delete removes (D6/D10).
        self._link_store.remove_tags(command.workspace_id, command.finding_id, tuple(remove_ids))
        self._link_store.add_tags(
            command.workspace_id,
            command.finding_id,
            tuple(add_ids),
            actor_id=command.actor_id,
            source="user",
        )

        logger.info(
            "finding_tagged workspace_id=%s finding_id=%s added=%s removed=%s actor_id=%s",
            command.workspace_id,
            command.finding_id,
            len(add_ids),
            len(remove_ids),
            command.actor_id,
        )
        return TagFindingResult(
            finding_id=command.finding_id,
            tags=self._link_store.refs_for_finding(command.workspace_id, command.finding_id),
        )
