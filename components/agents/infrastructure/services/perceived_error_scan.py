"""SEE-205 — scan recent conversations for perceived-error signals and surface
them as findings on the Agents board.

Online eval without ground truth: the perceived-error heuristic
(``domain.detectors.perceived_error``) reads the transcript; this service feeds
it real conversations and, for each one the user pushed back on, emits a finding
through the same ``persist_finding_as_task`` path the specialist detectors use.
Idempotent per conversation, so re-runs don't duplicate a finding.

Runnable ad hoc or on a schedule via the ``scan_perceived_errors`` management
command; it reuses the Agents-board setup the detector cycle performs.
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MAX_CONVERSATIONS = 50


def scan_workspace_for_perceived_errors(
    workspace_id,
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
) -> int:
    """Emit a finding for each recent conversation the user pushed back on.

    Returns the number of findings created (idempotent replays return 0 for an
    already-surfaced conversation).
    """
    from django.utils import timezone

    from components.agents.application.facades.agent_permissions_facade import (
        ensure_agents_team,
        ensure_ai_identity,
    )
    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )
    from components.agents.domain.detectors.perceived_error import (
        detect_perceived_errors,
    )
    from components.agents.infrastructure.services.agents_board_service import SUGGESTED
    from infrastructure.persistence.ai.conversations.models import ConversationMessage
    from infrastructure.persistence.workspaces.models import Workspace

    workspace = Workspace.objects.filter(id=workspace_id).first()
    if workspace is None:
        return 0

    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    recent_conversation_ids = list(
        ConversationMessage.objects.filter(conversation__metadata__workspace_id=str(workspace_id),
            created_at__gte=cutoff,)
        .values_list("conversation_id", flat=True)
        .distinct()[:max_conversations]
    )
    if not recent_conversation_ids:
        return 0

    rows = (
        ConversationMessage.objects.filter(conversation_id__in=recent_conversation_ids)
        .order_by("conversation_id", "created_at")
        .values("conversation_id", "role", "content", "created_at")
    )
    by_conversation: dict = {}
    for row in rows:
        by_conversation.setdefault(row["conversation_id"], []).append(row)

    # Flag conversations first, so we only pay for the board setup when there is
    # something to surface.
    to_surface = []
    for conversation_id, messages in by_conversation.items():
        flagged = detect_perceived_errors([{"role": m["role"], "content": m["content"]} for m in messages])
        recent_flags = [f for f in flagged if messages[f.index]["created_at"] >= cutoff]
        if recent_flags:
            to_surface.append((conversation_id, recent_flags))

    if not to_surface:
        return 0

    _teammate, ai_user = ensure_ai_identity(workspace)
    ensure_agents_team(workspace, ai_user)
    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    created = 0
    for conversation_id, recent_flags in to_surface:
        first = recent_flags[0]
        try:
            task_id = persist_finding_as_task(
                workspace=workspace,
                suggested_column=suggested_column,
                ai_user_id=ai_user_id,
                title="AI answer flagged by a user",
                summary=(
                    f"A user pushed back on the assistant in this conversation "
                    f"({len(recent_flags)} turn(s)) — {first.reason}. "
                    "Review the trace to improve the agent."
                ),
                source_type="ai.perceived_error",
                agent_type="workspace_agent",
                detector_key="perceived_error",
                payload_data={
                    "conversation_id": str(conversation_id),
                    "flagged_turns": len(recent_flags),
                    "reason": first.reason,
                    "assistant_snippet": first.assistant_snippet,
                    "user_snippet": first.user_snippet,
                },
                context={"conversation_id": str(conversation_id)},
                impact_score=2,
                idempotency_key=f"perceived_error:{conversation_id}",
            )
        except Exception:
            logger.exception(
                "perceived_error_persist_failed workspace_id=%s conversation_id=%s",
                workspace_id,
                conversation_id,
            )
            continue
        if task_id is not None:
            created += 1

    logger.info(
        "perceived_error_scan workspace_id=%s flagged=%s created=%s",
        workspace_id,
        len(to_surface),
        created,
    )
    return created
