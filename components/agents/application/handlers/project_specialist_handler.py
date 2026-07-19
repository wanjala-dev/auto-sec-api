"""Project specialist: turn ``ProjectCreated`` into a setup-nudge task
on the workspace's AI agent team Kanban.

Action List item P1 #24. Third specialist through the Phase 3
``SubscriptionRegistry`` — subscribes to ``ProjectCreated`` (published
from ``CreateProjectUseCase`` after the underlying port succeeds) and
posts a one-line "Set up <Project>" card to the Suggested column so a
fresh project doesn't sit configured-but-empty.

This is intentionally a thin starter specialist; the value is the
hook, not the copy. A future PR can pile on more events
(``MilestoneCompleted``, ``ProjectArchived``) and route each to a
tailored finding using stacked ``@subscribes_to(...)`` decorators on
the same handler module.

Idempotency: ``(workspace, source_type, metadata.idempotency_key)``
where the key is ``project_id:<project_id>``. Replays from Celery
retries are no-ops.

Failure isolation: errors log with ``project_id`` and don't re-raise —
the project itself was already persisted; other ProjectCreated
subscribers run independently.
"""
from __future__ import annotations

import logging

from components.agents.application.handlers.specialist_persistence_service import (
    persist_finding_as_task,
)
from components.agents.application.subscription_registry_service import (
    subscribes_to,
)
from components.project.domain.events.project_created_event import (
    ProjectCreated,
)

logger = logging.getLogger(__name__)

AGENT_TYPE = "project_specialist"
DETECTOR_KEY = "project_created"
ACTION_TYPE = "project_created"


@subscribes_to(ProjectCreated)
def handle_project_created(event: ProjectCreated) -> None:
    """Post a setup-nudge task whenever a new project is created.

    Lazy imports keep the module import-cheap so the registry's
    ``bind_all`` call in ``apps.py.ready()`` doesn't drag the ORM into
    every worker bootstrap.
    """
    from infrastructure.persistence.workspaces.models import Workspace

    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )
    from components.agents.infrastructure.services.agents_board_service import (
        SUGGESTED,
    )

    if event.workspace_id is None:
        logger.info(
            "project_specialist_no_workspace project_id=%s",
            event.project_id,
        )
        return

    workspace = Workspace.objects.filter(id=event.workspace_id).first()
    if workspace is None:
        logger.warning(
            "project_specialist_workspace_missing project_id=%s "
            "workspace_id=%s",
            event.project_id, event.workspace_id,
        )
        return

    project_id_str = str(event.project_id)

    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    stripped_title = (event.title or "").strip()
    title_label = stripped_title if stripped_title else "Untitled project"
    title = f"Set up: {title_label}"
    summary = (
        f"A new project '{title_label}' was just created. Set up the "
        "initial columns, add the first few tasks, and confirm who's "
        "leading. A fresh project that sits empty for a week is the "
        "single best predictor of it never shipping."
    )
    finding_context = {
        "project_id": project_id_str,
        "team_id": str(event.team_id) if event.team_id is not None else None,
        "created_by_id": (
            str(event.created_by_id) if event.created_by_id is not None else None
        ),
        "project_title": title_label,
        "detector_key": DETECTOR_KEY,
    }
    payload_data = {
        "project_id": project_id_str,
        "title": title_label,
        "created_at": event.created_at.isoformat(),
    }

    try:
        task_id = persist_finding_as_task(
            workspace=workspace,
            suggested_column=suggested_column,
            ai_user_id=ai_user_id,
            title=title,
            summary=summary,
            source_type=f"ai.{ACTION_TYPE}",
            agent_type=AGENT_TYPE,
            detector_key=DETECTOR_KEY,
            payload_data=payload_data,
            context=finding_context,
            # Project setup nudges are informational, not urgent —
            # mid-board so variance/anomaly findings stay on top.
            impact_score=25,
            idempotency_key=f"project_id:{project_id_str}",
        )
        if task_id is None:
            logger.info(
                "project_specialist_replay_noop workspace_id=%s project_id=%s",
                workspace.id, project_id_str,
            )
            return
        logger.info(
            "project_specialist_task_persisted workspace_id=%s "
            "project_id=%s task_id=%s",
            workspace.id, project_id_str, task_id,
        )
    except Exception:
        logger.exception(
            "project_specialist_task_persist_failed workspace_id=%s "
            "project_id=%s",
            workspace.id, project_id_str,
        )
