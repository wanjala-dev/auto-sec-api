"""Unified chat use case: every message goes through the deep-agent pipeline.

Replaces the legacy ``WorkspaceChatUseCase`` + keyword router + direct
handlers + embedding fallback adapter.  The rules this file enforces:

1. Persona-level AI access (workspace_chat feature, daily quota).
2. Workspace AI enabled toggle.
3. Workspace entitlement for the target agent type.
4. Delegate execution to ``DeepPlanAndRunUseCase`` with
   ``sync_to_kanban=False`` (chat mode — no kanban side effect).
5. Extract the synthesiser's final answer from the run state.

Framework-free.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict

from components.agents.application.commands.agent_chat_command import (
    AgentChatCommand,
    AgentChatFailure,
    AgentChatSuccess,
)
from components.agents.application.commands.deep_run_command import (
    DeepPlanAndRunCommand,
    DeepRunFailure,
    DeepRunSuccess,
)
from components.agents.application.ports.entitlement_port import EntitlementPort
from components.agents.application.ports.session_memory_port import SessionMemoryPort
from components.agents.application.ports.workspace_ai_config_port import (
    WorkspaceAIConfigPort,
)
from components.agents.application.use_cases.deep_run_use_case import (
    DeepPlanAndRunUseCase,
)
from components.agents.domain.policies.persona_ai_access_policy import (
    AIFeature,
    PersonaAIAccessPolicy,
)
from components.shared_kernel.application.handlers import CommandHandler

logger = logging.getLogger(__name__)

_Result = AgentChatSuccess | AgentChatFailure

_persona_policy = PersonaAIAccessPolicy()


import re as _re

_STOPPED_MARKERS = (
    "stopped due to iteration limit",
    "stopped due to iteration",
    "stopped before completing the task",
    "stopped either due to reaching the iteration",
    "reaching the iteration limit or time limit",
)

# Orchestration internals the synthesizer tacks on that shouldn't be
# shown to a chat user.  Stripped at the end of extraction.
_TRAILING_NOISE_PATTERNS = (
    _re.compile(r"\s*GOAL_MET:\s*(yes|no)\s*\.?\s*", _re.IGNORECASE),
    _re.compile(r"\s*REPLAN_REQUESTED:\s*(yes|no)\s*\.?\s*", _re.IGNORECASE),
    _re.compile(
        r"\s*(one|two|three|four|five|[0-9]+)\s+artifacts?\s+"
        r"(were|was|has been|have been|is)\s+produced[^.\n]*\.\s*",
        _re.IGNORECASE,
    ),
)


def _strip_orchestration_noise(text: str) -> str:
    """Remove synthesizer metadata tags from the final user-facing answer."""
    cleaned = text or ""
    for pattern in _TRAILING_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    # Collapse any resulting multi-newlines or trailing whitespace.
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _looks_stopped(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _STOPPED_MARKERS)


def _extract_final_answer(state: dict) -> str:
    """Pull a human-readable answer out of the deep-run state.

    The synthesiser node writes ``state["final_output"]["answer"]``.
    When the LLM synthesiser obediently regurgitates a "worker was
    stopped" trace as the final answer, the resulting string is
    useless to the user — we treat that as "no answer" and fall back
    to intermediate content we can recover from the run.  Before
    returning, we strip synthesizer-side metadata (``GOAL_MET``,
    ``REPLAN_REQUESTED``, "N artifacts were produced") so none of it
    leaks into the chat bubble.
    """
    if not isinstance(state, dict):
        return ""
    final_output = state.get("final_output") or {}
    answer = final_output.get("answer") if isinstance(final_output, dict) else None
    if answer and not _looks_stopped(str(answer)):
        return _strip_orchestration_noise(str(answer))

    completed = state.get("completed_tasks") or []
    for entry in reversed(completed):
        summary = None
        if hasattr(entry, "summary"):
            summary = entry.summary
        elif isinstance(entry, dict):
            summary = entry.get("summary") or entry.get("result")
        if summary and not _looks_stopped(str(summary)):
            return _strip_orchestration_noise(str(summary))

    # Nothing usable — tell the caller the run didn't produce a
    # grounded answer so it can surface a specific error rather than
    # the LLM's "agent was stopped" rephrasing.
    return ""


def _persist_user_message_impl(
    *,
    conversation_id: str | None,
    user_id: str,
    workspace_id: str,
    agent_type: str,
    query: str,
) -> str | None:
    """Create/get a user-facing Conversation and append the user's query as a message.

    Returns the conversation id so the caller can keep using it for the
    assistant reply + thread continuity.  Failures are swallowed — chat
    should still work even if persistence hiccups.
    """
    try:
        from infrastructure.persistence.ai.conversations.models import (
            Conversation,
            ConversationMessage,
        )
    except Exception:
        logger.exception("Could not import Conversation models for chat persistence")
        return conversation_id

    try:
        conversation = None
        if conversation_id:
            conversation = Conversation.objects.filter(id=conversation_id).first()
        if conversation is None:
            conversation = Conversation.objects.create(
                id=conversation_id or None,
                user_id=user_id,
                title=(query or "").strip()[:80] or "Chat",
                metadata={
                    "workspace_id": workspace_id,
                    "agent_type": agent_type,
                    "source": "agent_chat",
                },
            )
        ConversationMessage.objects.create(
            conversation=conversation,
            role="human",
            content=query or "",
        )
        return str(conversation.id)
    except Exception:
        logger.exception(
            "Failed to persist user chat message for workspace %s", workspace_id
        )
        return conversation_id


def _persist_assistant_message_impl(
    *,
    conversation_id: str | None,
    content: str,
    metadata: dict | None = None,
) -> str | None:
    """Append an assistant message.  Returns the new ``ConversationMessage.id``.

    The ID is threaded back to the HTTP response so the UI can attach
    per-message thumbs-up/thumbs-down via
    ``POST /ai/conversations/<conv>/messages/<id>/feedback/``.

    The optional ``metadata`` dict is persisted to
    ``ConversationMessage.metadata`` (a JSONField). Today this carries
    ``{"sources": [...]}`` for the citations panel — see AI Fluency
    Wave 2 in the plan. Empty / falsy metadata writes ``{}`` so the
    server-side default behaviour is unchanged.
    """
    if not conversation_id or not content:
        return None
    try:
        from infrastructure.persistence.ai.conversations.models import (
            Conversation,
            ConversationMessage,
        )

        conversation = Conversation.objects.filter(id=conversation_id).first()
        if conversation is None:
            return None
        message = ConversationMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=content,
            metadata=metadata or {},
        )
        return str(message.id)
    except Exception:
        logger.exception(
            "Failed to persist assistant chat message for conversation %s",
            conversation_id,
        )
        return None


# Hard cap on chat-history turns we hand to the planner. Each turn
# can be a few hundred tokens (the assistant's full answer); the
# planner's prompt is already heavy with the agent catalog and
# retrieval grounding. 10 turns ≈ recent context without blowing the
# token budget. Older turns drop off naturally — anything load-bearing
# from earlier is captured in ``session_memory`` instead.
_MAX_HISTORY_TURNS_FOR_PLANNER = 10
# Truncate per-message content. A long assistant answer can be 2-3k
# tokens; carrying the last 10 of those into the planner doubles its
# input. 800 chars ≈ a paragraph or two — enough for the LLM to
# resolve "those tasks" / "the project" / "earlier" references.
_MAX_CHARS_PER_HISTORY_MESSAGE = 800


def _load_conversation_pdf_id(conversation_id: str | None) -> str | None:
    """Return the ``pdf_id`` stored on the conversation's metadata, if any.

    The library's "Summarize PDF" affordance bootstraps a Conversation
    via ``MemoryViewSet.create_conversation`` with
    ``metadata={"pdf_id": ..., "workspace_id": ...}``. Subsequent
    messages flow through the unified Deep Agent endpoint
    (``/ai/chat/agent-chat/``) carrying that conversation_id; the
    Deep Agent uses this helper to scope its RAG retriever to the
    specific document the user opened, rather than pulling from the
    whole workspace.

    Failure-safe: missing imports, missing row, or non-dict metadata
    all yield ``None`` and the chat falls back to workspace-wide
    retrieval (less accurate but still answers).
    """
    if not conversation_id:
        return None
    try:
        from infrastructure.persistence.ai.conversations.models import Conversation
    except Exception:  # noqa: BLE001
        return None
    try:
        row = (
            Conversation.objects.filter(id=conversation_id)
            .only("metadata")
            .first()
        )
    except Exception:  # noqa: BLE001
        return None
    if row is None or not isinstance(row.metadata, dict):
        return None
    pdf_id = row.metadata.get("pdf_id")
    return str(pdf_id) if pdf_id else None


def _load_conversation_history(
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    """Return up to the last N persisted turns for the planner.

    Format: ``[{"role": "human"|"assistant", "content": "..."}, ...]``
    in chronological order, truncated to the most recent
    ``_MAX_HISTORY_TURNS_FOR_PLANNER`` turns and per-message content
    capped at ``_MAX_CHARS_PER_HISTORY_MESSAGE`` chars.

    Why we load this in the use case rather than have the planner
    fetch it: the planner is framework-free (no Django imports) and
    runs against the LLM directly. The use case already has the
    conversation_id and the persistence layer; loading here keeps
    the read in the application layer where it belongs.
    """
    if not conversation_id:
        return []
    try:
        from infrastructure.persistence.ai.conversations.models import (
            ConversationMessage,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not import ConversationMessage for chat history load"
        )
        return []
    try:
        # Order DESC for the LIMIT, reverse client-side so the planner
        # sees turns chronologically (oldest → newest).
        rows = (
            ConversationMessage.objects.filter(conversation_id=conversation_id)
            .order_by("-created_at")
            .values_list("role", "content")[:_MAX_HISTORY_TURNS_FOR_PLANNER]
        )
        history = []
        for role, content in reversed(list(rows)):
            text = (content or "").strip()
            if not text:
                continue
            if len(text) > _MAX_CHARS_PER_HISTORY_MESSAGE:
                text = text[:_MAX_CHARS_PER_HISTORY_MESSAGE].rstrip() + "…"
            history.append({"role": role or "assistant", "content": text})
        return history
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to load conversation history for %s", conversation_id
        )
        return []


# Per-field budgets when assembling ``context.workspace_profile``.
# These cap how much of each owner-authored field the planner sees on
# every call. Together they bound the prompt-length blow-up to a few
# hundred extra tokens per call — small enough to keep the model's
# context budget comfortable on a long multi-turn chat.
_PROFILE_FIELD_BUDGETS: dict[str, int] = {
    "mission": 600,
    "vision": 600,
    "workspace_story": 600,
    "voice_tone": 64,
    "voice_guidelines": 600,
    "beneficiary_language_rules": 400,
    "custom_system_prompt_addendum": 1000,
    "assistant_name": 80,
}


def _truncate(text: str, budget: int) -> str:
    """Hard-cap ``text`` to ``budget`` chars with an ellipsis suffix.

    The conversation-history loader uses the same pattern (line ~268);
    keeping the helper local avoids cross-module coupling for a 5-line
    function.
    """
    text = (text or "").strip()
    if len(text) <= budget:
        return text
    return text[:budget].rstrip() + "…"


def _build_workspace_profile_context(
    workspace_id: str,
    ai_config: Any,
    brand_voice: Any = None,
) -> dict[str, str]:
    """Assemble the ``context.workspace_profile`` block for the planner.

    Reads three sources:

    - ``Workspace.mission``, ``Workspace.vision``, ``Workspace.workspace_story``
      — already-editable on the workspace settings page.
    - The brand kit's canonical voice (``voice_tone`` + ``voice_guidelines``)
      via the injected ``BrandVoicePort`` — the single voice home since the
      brand-kit expansion (formerly ``WorkspaceAIConfig.voice_tone``).
    - ``WorkspaceAIConfig.{beneficiary_language_rules,
      custom_system_prompt_addendum}`` — AI-fluency-specific copy that stays
      on the AI profile.

    Returns ``{}`` when nothing is set so the planner sees no
    ``context.workspace_profile`` key (empty profile = no instruction
    drift). Failure-safe: every fetch is wrapped so an ORM error never
    breaks the chat path.
    """
    profile: dict[str, str] = {}

    # ── Workspace fields (mission / vision / story) ─────────────────
    try:
        from infrastructure.persistence.workspaces.models import Workspace
    except Exception:  # noqa: BLE001
        Workspace = None  # type: ignore[assignment]

    if Workspace is not None and workspace_id:
        try:
            workspace = (
                Workspace.objects.filter(id=workspace_id)
                .only("mission", "vision", "workspace_story")
                .first()
            )
        except Exception:  # noqa: BLE001
            logger.debug("Could not load Workspace for profile context", exc_info=True)
            workspace = None
        if workspace is not None:
            for attr in ("mission", "vision", "workspace_story"):
                value = _truncate(getattr(workspace, attr, "") or "", _PROFILE_FIELD_BUDGETS[attr])
                if value:
                    profile[attr] = value

    # ── Canonical voice from the brand kit (port is failure-safe) ───
    if brand_voice is not None and workspace_id:
        try:
            voice = brand_voice.get(str(workspace_id)) or {}
        except Exception:  # noqa: BLE001
            logger.debug("Could not load brand voice for profile context", exc_info=True)
            voice = {}
        for attr, key in (("voice_tone", "tone"), ("voice_guidelines", "guidelines")):
            value = _truncate(str(voice.get(key) or ""), _PROFILE_FIELD_BUDGETS[attr])
            if value:
                profile[attr] = value

    # ── AI-fluency fields from WorkspaceAIConfig ────────────────────
    for attr in (
        "beneficiary_language_rules",
        "custom_system_prompt_addendum",
    ):
        raw = getattr(ai_config, attr, "") if ai_config is not None else ""
        value = _truncate(str(raw) or "", _PROFILE_FIELD_BUDGETS[attr])
        if value:
            profile[attr] = value

    # ── Assistant identity from the teammate profile ─────────────────
    # The workspace can rename its assistant (AITeammateProfile.display_name,
    # edited in Settings ▸ AI Assistant). Inject the name so the assistant
    # answers to it; the avatar is UI-only and never reaches the planner.
    # Same lazy-ORM + failure-safe pattern as the Workspace lookup above.
    # The config-JSON fallbacks mirror OrmTeammateProfileRepository's alias
    # resolution for legacy rows renamed before display_name was a column.
    if workspace_id:
        try:
            from infrastructure.persistence.ai.models import AITeammateProfile

            row = (
                AITeammateProfile.objects.filter(workspace_id=workspace_id)
                .only("display_name", "config")
                .first()
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "Could not load teammate profile for context", exc_info=True
            )
            row = None
        if row is not None:
            config = row.config if isinstance(row.config, dict) else {}
            profile_section = config.get("profile")
            name = (
                row.display_name
                or config.get("display_name")
                or (
                    profile_section.get("name")
                    if isinstance(profile_section, dict)
                    else None
                )
                or ""
            )
            name = str(name).strip()
            if name:
                profile["assistant_name"] = _truncate(
                    name, _PROFILE_FIELD_BUDGETS["assistant_name"]
                )

    return profile


class AgentChatUseCase(CommandHandler[AgentChatCommand]):
    """Runs every chat message through the deep-agent pipeline."""

    _persist_user_message = staticmethod(_persist_user_message_impl)
    _persist_assistant_message = staticmethod(_persist_assistant_message_impl)

    def __init__(
        self,
        *,
        deep_plan_and_run: DeepPlanAndRunUseCase,
        entitlement: EntitlementPort,
        ai_config_port: WorkspaceAIConfigPort | None = None,
        session_memory: SessionMemoryPort | None = None,
        brand_voice_port: Any = None,
    ) -> None:
        self._deep = deep_plan_and_run
        self._entitlement = entitlement
        self._ai_config_port = ai_config_port
        self._session_memory = session_memory
        self._brand_voice_port = brand_voice_port

    def handle(self, command: AgentChatCommand) -> Any:
        return self.execute(command)

    def _bump_workspace_usage(self, workspace_id: str, *, plan_id: str) -> None:
        """Increment the workspace's running message + token counters.

        Sums ``prompt_tokens + completion_tokens`` across every
        ``DeepRunLog`` row this plan wrote (planner LLM call plus one
        per worker LLM call). Falls back to ``tokens=0`` (count
        messages only) if the lookup fails — the workspace daily
        message cap still bites.
        """
        total_tokens = 0
        try:
            from components.agents.infrastructure.repositories.orm_deep_run_aggregator_repository import (
                OrmDeepRunAggregatorRepository,
            )

            agg = OrmDeepRunAggregatorRepository().aggregate_plan_totals(
                plan_id=plan_id
            )
            total_tokens = int((agg.get("prompt") or 0) + (agg.get("completion") or 0))
        except Exception:
            logger.debug(
                "Could not sum DeepRunLog tokens for plan %s — "
                "incrementing message count only",
                plan_id,
            )

        if self._ai_config_port is None:
            return
        self._ai_config_port.increment_workspace_usage(
            workspace_id,
            messages=1,
            tokens=total_tokens,
        )

    def execute(self, command: AgentChatCommand) -> _Result:
        ws_id = str(command.workspace_id)
        conv_id = str(command.conversation_id) if command.conversation_id else None
        agent_type = command.agent_type or "workspace_agent"
        # Default to None so the workspace-profile injection at the
        # planner call site can read ``ai_config`` even when the port
        # is unavailable (CLI smoke runs, tests with mocked ports).
        ai_config = None

        # SEE-202 — emergency kill switch. An operator trip halts AI for all
        # workspaces (or one) without a deploy; new chat runs refuse at 503.
        from components.agents.application.policies.ai_kill_switch import (
            is_ai_killed,
        )

        if is_ai_killed(ws_id):
            return AgentChatFailure(
                error="AI is temporarily unavailable. Please try again shortly.",
                workspace_id=ws_id,
                query=command.query,
                agent_type=agent_type,
                conversation_id=conv_id,
                status_code=503,
            )

        # 1. Workspace AI config + persona check
        if self._ai_config_port is not None:
            try:
                ai_config = self._ai_config_port.load(ws_id)
            except Exception:
                logger.debug("Failed to load AI config for workspace %s", ws_id)
                ai_config = None

            if ai_config is not None:
                if not ai_config.ai_enabled:
                    return AgentChatFailure(
                        error="AI is disabled for this workspace. Contact the workspace owner to enable it.",
                        workspace_id=ws_id,
                        query=command.query,
                        agent_type=agent_type,
                        conversation_id=conv_id,
                        status_code=403,
                    )

                persona_role = command.persona_role or "contributor"
                try:
                    messages_today = self._ai_config_port.get_messages_used_today(
                        ws_id, str(command.user_id)
                    )
                except Exception:
                    messages_today = 0
                # Workspace-level usage drives the GTM cost gate (429).
                # The check is wired through the policy alongside the
                # existing per-persona cap so both stack: a chatty user
                # hits their per-seat limit first; an active org hits
                # the shared workspace pool before any one user does.
                try:
                    workspace_messages_today = (
                        self._ai_config_port.get_workspace_messages_today(ws_id)
                    )
                except Exception:
                    workspace_messages_today = 0
                try:
                    workspace_tokens_this_month = (
                        self._ai_config_port.get_workspace_tokens_this_month(ws_id)
                    )
                except Exception:
                    workspace_tokens_this_month = 0

                feature_access = _persona_policy.check_feature_access(
                    persona_role=persona_role,
                    feature=AIFeature.WORKSPACE_CHAT,
                    config=ai_config,
                    messages_used_today=messages_today,
                    workspace_messages_today=workspace_messages_today,
                    workspace_tokens_this_month=workspace_tokens_this_month,
                )
                if not feature_access.is_allowed:
                    # Workspace-level caps surface as 429 (rate-limit
                    # / quota exceeded) with the remaining-budget
                    # snapshot in ``quota_info`` so the chat header
                    # can render an accurate "resets at X" banner.
                    # Per-persona / config refusals stay at 403 — the
                    # workspace owner can change those, so it's a
                    # permission decision, not a usage cap.
                    if feature_access.is_workspace_quota_exceeded:
                        return AgentChatFailure(
                            error=feature_access.reason,
                            workspace_id=ws_id,
                            query=command.query,
                            agent_type=agent_type,
                            conversation_id=conv_id,
                            status_code=429,
                            quota_info={
                                "decision": str(feature_access.decision),
                                "workspace_daily_remaining_messages": (
                                    feature_access.workspace_daily_remaining_messages
                                ),
                                "workspace_monthly_remaining_tokens": (
                                    feature_access.workspace_monthly_remaining_tokens
                                ),
                                "workspace_daily_message_budget": (
                                    ai_config.workspace_daily_message_budget
                                ),
                                "workspace_monthly_token_budget": (
                                    ai_config.monthly_token_budget
                                ),
                            },
                        )
                    return AgentChatFailure(
                        error=feature_access.reason,
                        workspace_id=ws_id,
                        query=command.query,
                        agent_type=agent_type,
                        conversation_id=conv_id,
                        status_code=403,
                    )
                agent_access = _persona_policy.check_agent_access(
                    persona_role=persona_role,
                    agent_type=agent_type,
                    config=ai_config,
                )
                if not agent_access.is_allowed:
                    return AgentChatFailure(
                        error=agent_access.reason,
                        workspace_id=ws_id,
                        query=command.query,
                        agent_type=agent_type,
                        conversation_id=conv_id,
                        status_code=403,
                    )

        # 2. Workspace-level entitlement
        if not self._entitlement.is_agent_enabled_for_workspace(ws_id, agent_type):
            return AgentChatFailure(
                error="Agent is not enabled for this organization.",
                workspace_id=ws_id,
                query=command.query,
                agent_type=agent_type,
                conversation_id=conv_id,
                status_code=403,
            )

        # 3. Build agent_config for the deep run.
        # Tool-calling is the default — every ``@tool``-decorated method
        # is now promoted to a ``StructuredTool`` whose schema the LLM's
        # native function-calling API can populate. ReAct stays available
        # as a fallback (set ``use_react_agent=True`` to opt in) for
        # models that don't advertise function-calling, but chat itself
        # never asks for it. ReAct's parser-fragility was the root of
        # the 2026-05-08 hallucination cascade — see
        # ``docs/incidents/2026-05-08-chat-reliability-cascade.md`` and
        # ``docs/plans/AGENT_TOOL_COVERAGE_AUDIT.md``.
        agent_config: dict = {
            "default_user_id": str(command.user_id),
            "default_user_email": command.user_email,
        }
        if command.user_full_name:
            agent_config["default_user_name"] = command.user_full_name
        if command.username:
            agent_config["default_username"] = command.username
        if command.agent_config_extra:
            agent_config.update(command.agent_config_extra)

        if self._session_memory is not None:
            try:
                memory = self._session_memory.load(ws_id, agent_type)
                context_str = memory.as_context_string(max_facts=15)
                if context_str:
                    agent_config["session_memory_context"] = context_str
            except Exception:
                logger.debug(
                    "Failed to load session memory for %s/%s", ws_id, agent_type
                )

        # 4a. Load prior chat turns BEFORE persisting the new user
        # message so the planner sees real context, not a parrot of
        # the goal it already has. Without this the planner is
        # stateless — Turn 2's "who is assigned to those 4 tasks?"
        # can't resolve "those 4 tasks" because Turn 1's Q+A never
        # reaches it. Henry hit this 2026-05-08.
        conversation_history = _load_conversation_history(conv_id)

        # 4b. Persist the user-facing conversation + user message
        # before dispatching.  The deep run's worker will create its
        # own "Run Context" conversations internally (tagged
        # ``metadata.internal = True``) for its ReAct scratchpad —
        # those stay hidden from the thread list.  The conversation
        # we own here is the one the chat UI displays.
        user_conv_id = self._persist_user_message(
            conversation_id=conv_id,
            user_id=str(command.user_id),
            workspace_id=ws_id,
            agent_type=agent_type,
            query=command.query,
        )
        conv_id = user_conv_id or conv_id

        # 5. Kick off the deep run.
        # Prefer a client-supplied plan_id when present so the chat UI's
        # ``resource.agent_run.<plan_id>`` WebSocket subscription
        # (opened *before* this request) lands on the same group the
        # orchestrator's ``ctx.info()`` / ``ctx.report_progress()``
        # events are published to. Without this the UI would only learn
        # the plan_id at HTTP-response time — i.e. after the run was
        # already over — and the live-feedback bubble would have
        # nothing to show. Falls back to a generated UUID so older
        # callers (CLI, tests) still work unchanged.
        plan_id = str(command.plan_id) if command.plan_id else str(_uuid.uuid4())
        # Hand the planner the prior turns under ``conversation_history``.
        # The planner system prompt teaches the LLM to use this when
        # resolving cross-turn references ("those tasks", "the project
        # we discussed"). Empty list on first turn — no harm.
        planner_extra_context: Dict[str, Any] = {}
        if conversation_history:
            planner_extra_context["conversation_history"] = conversation_history

        # Inject the workspace owner's authored profile (mission, vision,
        # voice tone, beneficiary-language rules, custom addendum) so the
        # planner anchors the plan to this org's actual context. Missing
        # / empty profile = no key set, planner falls back to its
        # registered-agent defaults. See AI Fluency Wave 1 in the
        # atomic-gathering-fox plan.
        workspace_profile = _build_workspace_profile_context(
            ws_id, ai_config, self._brand_voice_port
        )
        if workspace_profile:
            planner_extra_context["workspace_profile"] = workspace_profile

        # When the conversation was opened from the library's "Summarize
        # PDF" affordance, the Conversation row carries the pdf_id in its
        # metadata. Forward it to the deep service so RAG scopes to the
        # specific document — the planner sees only that PDF's chunks as
        # retrieved_context, and the resulting answer is anchored to the
        # document the user actually opened. ``deep_service.plan_and_run_with_llm``
        # pops this key before the rest of ``extra_context`` reaches the
        # planner prompt.
        scoped_pdf_id = _load_conversation_pdf_id(conv_id)
        if scoped_pdf_id:
            planner_extra_context["pdf_id"] = scoped_pdf_id

        # Honour the workspace owner's model choice from
        # ``WorkspaceAIConfig.preferred_model`` when set. The
        # ``DeepPlanAndRunCommand.model_name`` field is already plumbed
        # through to ``plan_with_llm`` (see deep_run_use_case.py:109);
        # we just need to surface the configured value at this layer.
        # Empty string means "no preference, LLMFactory picks default"
        # — matches the model picker in AISetupForm where an unset
        # workspace falls through to the platform default.
        preferred_model = (
            getattr(ai_config, "preferred_model", "") or ""
        ).strip() or None

        deep_command = DeepPlanAndRunCommand(
            goal=command.query,
            agent_type=agent_type,
            user_id=str(command.user_id),
            workspace_id=ws_id,
            plan_id=plan_id,
            agent_config=agent_config,
            model_name=preferred_model,
            sync_to_kanban=False,
            extra_context=planner_extra_context or None,
        )
        result = self._deep.execute(deep_command)

        if isinstance(result, DeepRunFailure):
            self._persist_assistant_message(
                conversation_id=conv_id,
                content=f"[error] {result.error}",
            )
            return AgentChatFailure(
                error=result.error,
                workspace_id=ws_id,
                query=command.query,
                agent_type=agent_type,
                conversation_id=conv_id,
                status_code=result.status_code or 500,
            )

        assert isinstance(result, DeepRunSuccess)  # type narrow
        answer = _extract_final_answer(result.state)
        if not answer:
            self._persist_assistant_message(
                conversation_id=conv_id,
                content=(
                    "Sorry — I finished the run but couldn't produce a "
                    "response.  Try a more specific question."
                ),
            )
            return AgentChatFailure(
                error=(
                    "The deep agent finished without producing a response. "
                    "Try a more specific question or check that the workspace "
                    "has been indexed."
                ),
                workspace_id=ws_id,
                query=command.query,
                agent_type=agent_type,
                conversation_id=conv_id,
                status_code=422,
            )
        # Pull the RAG chunks the planner used (re-attached by
        # ``deep_service.plan_and_run_with_llm``) so we can persist
        # them onto the assistant message and surface them in the
        # response. Failure-safe: a non-list / missing key yields an
        # empty list, which the persist call coalesces to ``{}``.
        sources = result.state.get("retrieved_sources") or []
        if not isinstance(sources, list):
            sources = []
        assistant_metadata = {"sources": sources} if sources else None

        message_id = self._persist_assistant_message(
            conversation_id=conv_id,
            content=answer,
            metadata=assistant_metadata,
        )

        # Bump the workspace's daily-messages + monthly-tokens counters
        # only after a successful chat reply — failed chats don't burn
        # quota. Tokens come from the DeepRunLog rows the planner and
        # workers wrote during this run. Failure to track quota must
        # NOT break the user-facing response — we'd rather under-count
        # than 500 a successful answer, so the whole block is best-effort.
        try:
            self._bump_workspace_usage(ws_id, plan_id=result.plan_id)
        except Exception:
            logger.exception(
                "Failed to increment workspace AI quota for ws=%s plan=%s",
                ws_id,
                result.plan_id,
            )

        return AgentChatSuccess(
            response=answer,
            workspace_id=ws_id,
            query=command.query,
            agent_type=agent_type,
            sources=sources,
            plan_id=result.plan_id,
            message_id=message_id,
            conversation_id=conv_id,
            source="deep_agent",
        )
