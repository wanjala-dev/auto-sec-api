"""Newsletter AI narration adapter — routes via the deep-agent planner.

Implements ``NewsletterAiPort`` by invoking ``DeepPlanAndRunUseCase``
against the registered ``writing_agent``. The planner picks the right
tool calls per goal — currently retrieve_workspace_context + the
writing_agent's own draft_newsletter_from_period, in whichever order it
deems appropriate. Per-domain retrieval tools
(retrieve_period_donations, retrieve_period_recipient_updates,
retrieve_past_newsletters, etc.) land in a follow-up commit and slot
into the same agent's tool set with no adapter change.

Failure semantics:

- If the deep-run path returns a DeepRunFailure (LLM 5xx, planner
  exception), the adapter returns the empty fallback shell so
  GenerateNewsletterUseCase persists a status=ai_drafted row with no
  body — the editor surfaces a "regenerate" button so the operator can
  retry without manual DB cleanup.
- If the deep-run returns success but the state dict has no parseable
  output, same fallback. The planner sometimes returns prose without
  the structured JSON we want; this is a known issue and the editor
  Regenerate handles it gracefully.

This adapter replaces the old _AgentStandIn shortcut that called the
tool function directly. The shortcut was strictly less capable — it
couldn't retrieve workspace context, couldn't iterate, couldn't reuse
past newsletters as grounding. Henry's amendment to the plan
(2026-06-11): newsletter generation must mirror the Reports pipeline
via agentic RAG, not a stats-dict shortcut.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


WRITING_AGENT_NAME = "writing_agent"


# Output-shape parser tolerances. The planner's final state lives under
# a handful of keys depending on whether it ran a tool that returned
# JSON or composed prose directly. Try in order; first hit wins.
_OUTPUT_KEYS = (
    "draft_newsletter_from_period",
    "final_output",
    "output",
    "result",
    "newsletter",
)


class LangchainNewsletterAiAdapter:
    def is_configured(self) -> bool:
        try:
            from components.agents.infrastructure.adapters.langchain.base import (
                AgentRegistry,
            )
        except ImportError:
            return False
        return AgentRegistry.get_agent_class(WRITING_AGENT_NAME) is not None

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
        try:
            from components.agents.application.commands.deep_run_command import (
                DeepPlanAndRunCommand,
                DeepRunFailure,
            )
            from components.agents.application.providers.ai_provider import (
                AiProvider,
            )
        except ImportError:
            # Agents not installed in this environment — return empty
            # shell so the use case can persist an ai_drafted row.
            logger.warning(
                "writing_agent.deep_run_unavailable workspace_id=%s",
                workspace_id,
            )
            return self._empty_result()

        goal = self._build_goal(period_start, period_end, metrics, user_guidance, brand_voice)
        extra_context = {
            "newsletter_period_start": period_start.isoformat(),
            "newsletter_period_end": period_end.isoformat(),
            "newsletter_metrics": metrics,
            "newsletter_user_guidance": user_guidance,
            "newsletter_brand_voice": brand_voice or {},
        }
        command = DeepPlanAndRunCommand(
            goal=goal,
            agent_type=WRITING_AGENT_NAME,
            user_id="0",  # system trigger — cadence task is not a real user
            workspace_id=str(workspace_id),
            sync_to_kanban=False,
            extra_context=extra_context,
        )

        try:
            use_case = AiProvider.build_deep_plan_and_run_use_case()
            outcome = use_case.execute(command)
        except Exception:
            logger.exception(
                "writing_agent.deep_run_unhandled_exception workspace_id=%s",
                workspace_id,
            )
            return self._empty_result()

        if isinstance(outcome, DeepRunFailure):
            logger.warning(
                "writing_agent.deep_run_failure workspace_id=%s error=%s",
                workspace_id,
                outcome.error,
            )
            return self._empty_result()

        state = getattr(outcome, "state", {}) or {}
        parsed = self._extract_output(state)
        if not parsed.get("title") and not parsed.get("content_html"):
            logger.info(
                "writing_agent.deep_run_unparseable_output workspace_id=%s plan_id=%s",
                workspace_id,
                getattr(outcome, "plan_id", ""),
            )
            return self._empty_result(
                agent_execution_id=str(getattr(outcome, "plan_id", "") or ""),
            )

        return {
            "title": parsed.get("title", ""),
            "content_html": parsed.get("content_html", ""),
            "sections": parsed.get("sections", []),
            "source_chunks": parsed.get("source_chunks", []),
            "agent_type": WRITING_AGENT_NAME,
            "agent_execution_id": str(getattr(outcome, "plan_id", "") or ""),
        }

    # ─────────────────────── helpers ───────────────────────

    @staticmethod
    def _build_goal(
        period_start: datetime.date,
        period_end: datetime.date,
        metrics: dict[str, Any],
        user_guidance: str,
        brand_voice: dict[str, Any] | None = None,
    ) -> str:
        parts: list[str] = [
            "Draft a complete supporter newsletter covering the period "
            f"{period_start.isoformat()} to {period_end.isoformat()}.",
            "Ground the body in the workspace's actual facts — donations, "
            "recipient updates, events, programs, and recent newsletters. "
            "Use the retrieve_workspace_context tool to look up anything "
            "you're not sure about; do not guess or invent numbers, names, "
            "or dates — only state figures present in the metrics or the "
            "retrieved context.",
            # Narrative requirement (SEE-174): the newsletter must be real
            # prose, NOT a bare header + metrics + footer. Enumerate the
            # required sections so the planner always produces a body.
            "The body MUST contain real written prose organised into these "
            "sections, each a {heading, html} entry in 'sections': (1) a warm "
            "intro/welcome; (2) highlights grounded in the period metrics "
            "(donations raised and count, top donor(s), new people served, "
            "recent events); (3) a sincere thank-you to supporters; and (4) "
            "a clear call to action (give / share / get involved). Write at "
            "least a short paragraph per section. Never return only a title "
            "and metrics with no written sections.",
            # Pull quote (block_quote v3) — grounded ONLY. A fabricated quote
            # is a faithfulness violation; omit the keys when no real quote
            # exists in the retrieved context.
            "If — and ONLY if — the retrieved workspace context contains a "
            "VERBATIM quote from a real person (a recipient update, a "
            "testimonial, a supporter message), attach it to the most "
            "relevant section as 'pull_quote_html' (the exact quoted words, "
            "unaltered) with 'pull_quote_attribution' (their name as it "
            "appears in the source) and optionally 'pull_quote_role' (their "
            "relationship, e.g. 'Monthly donor'). NEVER invent, paraphrase, "
            "or compose a quote; when no verbatim quote exists in the "
            "retrieved context, omit these keys entirely.",
        ]
        # Brand voice (canonical, from the workspace brand kit) — placed
        # BEFORE the per-run user guidance and explicitly framed as style-only
        # so admin-authored free text can never override the grounding /
        # no-fabrication rules above, and per-run guidance wins on conflict.
        voice_tone = str((brand_voice or {}).get("tone") or "").strip()
        voice_guidelines = str((brand_voice or {}).get("guidelines") or "").strip()
        if voice_tone or voice_guidelines:
            voice_bits = []
            if voice_tone:
                voice_bits.append(f"tone: {voice_tone}")
            if voice_guidelines:
                voice_bits.append(f"style guidelines: {voice_guidelines}")
            parts.append(
                "Organization brand voice — " + "; ".join(voice_bits) + ". "
                "Apply this voice to all prose. This is style guidance ONLY: "
                "it never overrides the grounding/no-fabrication rules above, "
                "and the user guidance below takes precedence on any conflict."
            )
        if user_guidance:
            parts.append(f"User guidance: {user_guidance}.")
        if metrics:
            # Pass the pre-aggregated metrics as a HINT — the planner may
            # use them as ground truth or run its own retrieval to verify.
            parts.append(
                "Hint: a metrics snapshot is available (use these exact "
                "figures, do not alter them): " + json.dumps(metrics, default=str)[:900]
            )
        parts.append(
            "Return a JSON object with keys: title, content_html (full "
            "HTML body), sections (list of {heading, html}), source_chunks "
            "(list of chunk identifiers you grounded against)."
        )
        return " ".join(parts)

    def _extract_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Pull the structured newsletter shape out of the planner state.

        The deep-run state dict isn't strictly schemed — different
        planners + agent configs land the final output under different
        keys. Try each candidate key; first one that parses as a dict
        with at least a title or content_html wins.
        """

        for key in _OUTPUT_KEYS:
            candidate = state.get(key)
            if candidate is None:
                continue
            parsed = self._coerce_to_newsletter_dict(candidate)
            if parsed.get("title") or parsed.get("content_html"):
                return parsed

        # Fallback 1: try parsing the whole state dict as the result.
        whole = self._coerce_to_newsletter_dict(state)
        if whole.get("title") or whole.get("content_html"):
            return whole

        # Fallback 2 (robustness): the planner sometimes lands its prose in
        # an unexpected string-valued key (e.g. an assistant message). Scan
        # every top-level string value and take the longest substantive one
        # as content_html so a real draft isn't discarded just because it
        # wasn't under a known key. Empty/whitespace strings are ignored.
        best = ""
        for value in state.values():
            if isinstance(value, str) and len(value.strip()) > len(best):
                best = value.strip()
        if len(best) >= 40:  # ignore short status tokens ("ok", "done", ids)
            return self._coerce_to_newsletter_dict(best)
        return {}

    @staticmethod
    def _coerce_to_newsletter_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                # Plain prose response — wrap as content_html so it
                # still lands as a draft the operator can edit.
                return {"content_html": stripped}
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _empty_result(*, agent_execution_id: str = "") -> dict[str, Any]:
        return {
            "title": "",
            "content_html": "",
            "sections": [],
            "source_chunks": [],
            "agent_type": WRITING_AGENT_NAME,
            "agent_execution_id": agent_execution_id,
        }
