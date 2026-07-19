"""Port for AI narration of newsletter drafts.

Mirrors ``components.reports.application.ports.financial_report_ai_port`` —
the writing_agent fans workspace metrics into a coherent newsletter body.
"""

from __future__ import annotations

import datetime
from typing import Any, Protocol


class NewsletterAiPort(Protocol):
    def is_configured(self) -> bool:
        """True if the AI backend is reachable and has credentials."""
        ...

    def draft_newsletter(
        self,
        *,
        workspace_id: str,
        period_start: datetime.date,
        period_end: datetime.date,
        metrics: dict[str, Any],
        user_guidance: str = "",
        brand_voice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce a newsletter draft.

        ``brand_voice`` is the workspace's canonical voice
        (``{"tone", "guidelines"}``) — STYLE steering only, never grounding;
        ``None`` when the workspace has no voice set.

        Returns a dict with at minimum:
            - title: str
            - content_html: str
            - sections: list[dict] (each carrying ``heading`` + ``body_html``)
            - agent_type: str
            - agent_execution_id: str
        """
        ...
