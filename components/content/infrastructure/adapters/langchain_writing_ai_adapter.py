"""AI-assist adapter for the editor's AskAi button (SEE-169).

Routes the editor "Ask AI" path through the grounded, NON-persisting
``GenerateInteractiveDraftUseCase`` in the agents application layer
(via ``AIProvider``), exactly the way ``LangchainNewsletterAiAdapter``
routes the cadence path through ``AIProvider.build_deep_plan_and_run_use_case``.

Why this shape (the deep fix, not a bandaid):

- The previous implementation used an ``_AgentStandIn`` to call the
  ``writing_agent`` tool functions directly. Those tools self-persist a
  ``WritingDraft`` row on every invocation — so "Ask AI" on an open
  document spawned an orphan draft, and produced ungrounded copy
  (``metrics={}``, no RAG, no document context).
- The tools' self-persistence is a *legitimate* feature for the global
  orchestrator chat surface ("draft a thank-you" → "Open in Writing →"
  card), so it stays. The editor path simply stops touching them.
- The new use case retrieves workspace RAG context (the same
  ``WorkspaceRetrievalPort`` the planner prefetch uses), grounds the
  prompt in it + the open document's title/recipient/topic/intent, and
  returns body text WITHOUT persisting. No orphan rows by construction.

The return shape is unchanged from the controller's perspective
(``{title, body_html, excerpt, sections, agent_type}``) with an added
``source_chunks`` provenance list (harmless extra field).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


WRITING_AGENT_NAME = "writing_agent"


class LangchainWritingAiAdapter:
    def is_configured(self) -> bool:
        """True when the agents application provider (and thus the LLM +
        retrieval ports it wires) is importable in this environment."""
        try:
            from components.agents.application.providers.ai_provider import (  # noqa: F401
                AIProvider,
            )
            from components.knowledge.application.providers.ai_llm_provider import (  # noqa: F401
                AILlmProvider,
            )
        except ImportError:
            return False
        return True

    def draft_for_kind(
        self,
        *,
        kind: str,
        workspace_id: str,
        prompt: str,
        title: str = "",
        recipient_name: str = "",
        period_start: datetime.date | None = None,
        period_end: datetime.date | None = None,
        topic: str = "",
        tone: str = "warm",
        related_entity_type: str = "",
        related_entity_id: str = "",
        grounding_file_ids: list[str] | None = None,
        existing_body_html: str = "",
        existing_layout: dict[str, Any] | None = None,
        conversation: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Generate grounded body text for the OPEN document via the
        interactive-draft use case. Persists nothing.

        Returns a dict with at least ``title`` + ``body_html``; kind-
        specific extras (``excerpt`` for blogs, ``sections`` for
        newsletters) and ``source_chunks`` (provenance) pass through.
        """

        context: dict[str, Any] = {
            "title": title,
            "prompt": prompt,
            "recipient_name": recipient_name,
            "topic": topic,
            "tone": tone or "warm",
            "period_start": period_start.isoformat() if period_start else "",
            "period_end": period_end.isoformat() if period_end else "",
            "related_entity_type": related_entity_type,
            "related_entity_id": related_entity_id,
            # Author-selected uploaded documents (task #16) — the use case
            # retrieves these files directly so they lead the grounding set.
            "grounding_file_ids": [str(i) for i in (grounding_file_ids or []) if i],
            # The open document's current body (task #17) — when it is a
            # template scaffold, the use case instructs the model to
            # COMPLETE it (fill placeholders) instead of drafting blind.
            "existing_body_html": existing_body_html or "",
            # Designed documents (task #19): the draft's block layout — the
            # use case has the model COMPLETE its text fields and returns
            # the completed layout alongside body_html.
            "existing_layout": existing_layout if isinstance(existing_layout, dict) else None,
            # Chat continuity (task #31): recent assist-session turns so a
            # follow-up instruction keeps its context. Pre-capped by the
            # controller.
            "conversation": conversation or [],
        }

        try:
            from components.agents.application.providers.ai_provider import AIProvider

            use_case = AIProvider.build_generate_interactive_draft_use_case()
            result = use_case.execute(
                workspace_id=str(workspace_id),
                kind=kind,
                context=context,
            )
        except Exception:
            logger.exception(
                "writing_ai.draft_for_kind_failed kind=%s workspace_id=%s",
                kind,
                workspace_id,
            )
            result = {}

        # Normalise: every kind returns at least title + body_html.
        normalised = {
            "title": result.get("title", "") or title,
            "body_html": result.get("body_html") or result.get("content_html", ""),
            "excerpt": result.get("excerpt", ""),
            "sections": result.get("sections", []),
            "source_chunks": result.get("source_chunks", []),
            "faithfulness": result.get("faithfulness", {}),
            "agent_type": WRITING_AGENT_NAME,
        }
        if isinstance(result.get("layout"), dict):
            normalised["layout"] = result["layout"]
        return normalised
