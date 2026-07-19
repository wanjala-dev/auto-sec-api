"""Composition root / provider for the project-context query repository.

Controllers (`components/project/api/controller.py`) consume this provider
instead of importing the concrete `ProjectRepository` adapter directly.
This keeps the API layer's import graph free of
`components.project.infrastructure.*` symbols (Explicit Architecture
controller-→infrastructure boundary, enforced by the architecture test
suite).

The provider lazy-imports the adapter inside ``get_repository`` so this
module has no top-level infra import — module load stays cheap and tests
can monkeypatch ``_default`` (or the ``get_repository`` method) without
dragging Django ORM models into discovery.

The underlying ``ProjectRepository`` exposes a wide CRUD/read surface
(workspace, team, project, task, column, project-update, milestone,
task-comment, user lookup, project-entry creation, archival, etc.).
Rather than re-declare every method on the provider — which would
duplicate the repository surface and drift over time — the provider hands
back a fresh repository instance via ``get_repository()``. Callers keep
their existing ``repo.<method>(…)`` ergonomics; the boundary is enforced
because the controller no longer names the concrete adapter class.
"""

from __future__ import annotations

from typing import Any


class ProjectRepositoryProvider:
    """Driving-side façade for the project-context query repository."""

    def get_repository(self) -> Any:
        """Return a fresh ``ProjectRepository`` instance.

        Lazy-imports the concrete adapter so this module never pulls
        infrastructure at import time. The repository itself is stateless
        — each call returns a new instance, matching the pre-refactor
        ``ProjectRepository()`` semantics used throughout the controller.
        """
        from components.project.infrastructure.repositories.project_repository import (
            ProjectRepository,
        )

        return ProjectRepository()


_default = ProjectRepositoryProvider()


def get_project_repository_provider() -> ProjectRepositoryProvider:
    """Return the default provider — composition root for the project
    query repository. Override by monkeypatching this module's
    ``_default`` attribute (or the provider's ``get_repository`` method)
    in tests."""
    return _default
