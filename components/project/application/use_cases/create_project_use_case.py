"""Use case for creating a project.

No Django imports — depends only on application-layer ports.

Publishes a ``ProjectCreated`` domain event after a successful create,
enabling downstream subscribers (the project specialist handler,
analytics, notifications) to react without touching this code. The
publisher is optional: callers that don't want the event (legacy
tests, ad-hoc scripts) can omit it. Production wires it via the
``ProjectProvider``.
"""
from __future__ import annotations

from components.shared_kernel.domain.errors import ValidationError
from datetime import datetime, timezone
from uuid import UUID

from components.project.application.ports.create_project_port import (
    CreateProjectCommand,
    CreateProjectPort,
    CreateProjectResult,
)
from components.project.domain.events.project_created_event import (
    ProjectCreated,
)
from components.shared_kernel.application.ports.event_publisher import (
    EventPublisher,
)


class CreateProjectUseCase:
    def __init__(
        self,
        port: CreateProjectPort,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._port = port
        # Optional so existing tests / call sites that don't care
        # about the event continue to work unchanged. Production
        # wires this through ``ProjectProvider``.
        self._event_publisher = event_publisher

    def execute(self, *, command: CreateProjectCommand) -> CreateProjectResult:
        result = self._port.create_project(command=command)

        if (
            result.success
            and result.project is not None
            and self._event_publisher is not None
        ):
            try:
                event = _build_project_created_event(result.project, command)
                self._event_publisher.publish(event)
            except Exception:
                # The project itself was persisted — failing to publish
                # the event must NOT roll that back. Log and swallow so
                # the caller still sees the success result.
                import logging
                logging.getLogger(__name__).exception(
                    "project_created_event_publish_failed project=%s",
                    getattr(result.project, "id", None),
                )

        return result


def _build_project_created_event(
    project, command: CreateProjectCommand
) -> ProjectCreated:
    """Translate the ORM-shaped Project into the framework-free event.

    Defensive: handles workspace_id / team_id / created_by_id being
    missing or non-UUID — coerces to None so the event constructor's
    ``UUID | None`` typing stays honest.
    """

    def _as_uuid_or_none(value):
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    project_id = _as_uuid_or_none(getattr(project, "id", None))
    workspace_id = _as_uuid_or_none(
        getattr(project, "workspace_id", None) or command.workspace_id
    )
    team_id = _as_uuid_or_none(
        getattr(project, "team_id", None) or command.team_id
    )
    created_by_id = _as_uuid_or_none(
        getattr(project, "created_by_id", None) or command.user_id
    )
    created_at = (
        getattr(project, "created_at", None)
        or getattr(project, "created", None)
        or datetime.now(timezone.utc)
    )
    title = getattr(project, "title", None) or command.title or ""

    if project_id is None:
        raise ValidationError(
            "Cannot publish ProjectCreated without a project id"
        )

    return ProjectCreated(
        project_id=project_id,
        workspace_id=workspace_id,
        team_id=team_id,
        created_by_id=created_by_id,
        title=title,
        created_at=created_at,
    )
