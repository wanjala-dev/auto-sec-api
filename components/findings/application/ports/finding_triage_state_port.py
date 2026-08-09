"""Port: read the triage state of findings (shaped to what the findings read path needs).

The state lives on the board card, which the ``project`` context owns and the
``agents`` context writes. Findings needs it **read-only**, in bulk, for the page it
is about to serialize — so the port is shaped to exactly that (C3/C5: a port fits
the core's need, it does not mimic the other context's storage).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from components.findings.application.queries.finding_triage_state_query import FindingTriageStateView


class FindingTriageStatePort(ABC):
    @abstractmethod
    def states_for(self, *, workspace_id, finding_ids: Sequence[str]) -> dict[str, FindingTriageStateView]:
        """Return ``{finding_id: state}`` for the given findings.

        Implementations MUST resolve the whole batch in a constant number of queries
        — this feeds a paginated list, so a per-finding lookup would be an N+1 on
        every findings page. A finding with no board card is simply absent from the
        mapping; the caller derives the honest "not routed" state for it.
        """
