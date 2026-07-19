"""Cross-context entity fact-sheet port (SEE-170).

Today the editor draft only grounds via RAG chunks; entity-update kinds
(recipient_update, project_update, event_update, campaign_update) know the
linked entity's NAME but not its real data, so the model can fabricate the
recipient's age, a campaign's raised total, or an event's date.

This port lets the agents application core ask for a compact, structured
**fact sheet** of one entity's real data — without importing another
context's infrastructure. The application layer depends on this ABC; the
ORM adapter in ``infrastructure/adapters/`` reads the persistence models
and is wired in by ``AIProvider`` (the composition root).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EntityFactSheetPort(ABC):
    """Read-only structured facts for a single workspace entity."""

    @abstractmethod
    def fact_sheet(
        self, *, workspace_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        """Return a compact fact sheet for one entity, or ``{}``.

        Args:
            workspace_id: the workspace the entity must belong to (the
                lookup is workspace-scoped — cross-workspace ids return
                ``{}``).
            entity_type: the kind of entity — one of ``recipient`` /
                ``beneficiary``, ``project``, ``event``, ``campaign``,
                ``donor`` / ``sponsor``, ``funder`` / ``grant`` (aliases
                resolved by the adapter). Unknown types return ``{}``.
            entity_id: the entity's primary key.

        Returns:
            ``{}`` when the entity is missing, unknown, or unavailable.
            Otherwise a dict shaped::

                {
                    "entity_type": "recipient",
                    "entity_id": "<uuid>",
                    "name": "Amina Hassan",
                    "facts": [
                        "Name: Amina Hassan",
                        "Age: 12",
                        "Total raised: 45000.00",
                        ...
                    ],
                }

            ``facts`` is a list of human-readable ``"Label: value"`` lines.
            The use case injects them into the prompt's grounding block AND
            into the faithfulness grounding set, so figures sourced from the
            entity count as supported.
        """
