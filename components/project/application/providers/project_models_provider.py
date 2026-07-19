"""Provider for ORM model classes living in ``infrastructure.persistence.project``.

Controllers under ``components/*/api/`` consume :class:`ProjectModelsProvider`
instead of importing the Django ORM model classes directly. This keeps the
API / application layers' import graph free of infrastructure dependencies —
enforced by ``test_controllers_do_not_import_concrete_adapters`` and the
broader Explicit Architecture rules.

Every property below performs a **lazy** import of the underlying ORM class
so that this module stays framework-free at import time (only stdlib +
``typing`` imports at the top).
"""

from __future__ import annotations

from typing import Any


class ProjectModelsProvider:
    """Lazy accessor for project-context ORM model classes."""

    @property
    def Tag(self) -> Any:
        from infrastructure.persistence.project.models import Tag

        return Tag

    @property
    def ProjectMilestone(self) -> Any:
        from infrastructure.persistence.project.models import ProjectMilestone

        return ProjectMilestone

    @property
    def ProjectUpdate(self) -> Any:
        from infrastructure.persistence.project.models import ProjectUpdate

        return ProjectUpdate

    @property
    def Project(self) -> Any:
        from infrastructure.persistence.project.models import Project

        return Project

    @property
    def Column(self) -> Any:
        from infrastructure.persistence.project.models import Column

        return Column

    @property
    def Task(self) -> Any:
        from infrastructure.persistence.project.models import Task

        return Task

    @property
    def TaskComment(self) -> Any:
        from infrastructure.persistence.project.models import TaskComment

        return TaskComment

    @property
    def ProjectEntry(self) -> Any:
        from infrastructure.persistence.project.models import ProjectEntry

        return ProjectEntry


_default = ProjectModelsProvider()


def get_project_models_provider() -> ProjectModelsProvider:
    """Return the default :class:`ProjectModelsProvider`.

    Composition root for project ORM model lookups in controllers.
    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
