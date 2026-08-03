"""Port: mutate the agents context's ``AIPermissionGrant`` rows.

The AI-teammate facade's ``disable_teammate`` flips every permission grant a
workspace's AI principal holds to ``disabled`` when the teammate is turned off.
That bulk write used to reach ``infrastructure.persistence.ai`` ORM directly from
the application-layer facade — a Rule-2 violation (dependencies point inward).
This port is the sanctioned write seam; the ORM lives in the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AiPermissionGrantPort(ABC):
    """Write access to a workspace's AI permission grants."""

    @abstractmethod
    def disable_grants_for_principal(self, *, workspace: Any, principal: Any) -> int:
        """Mark every ``AIPermissionGrant`` for ``principal`` in ``workspace`` as
        disabled. Returns the number of rows updated.
        """
