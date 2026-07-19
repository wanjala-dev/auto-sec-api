"""Celery autodiscover shim for the workflow context.

``app.autodiscover_tasks()`` imports ``<installed_app>.tasks`` for every app in
INSTALLED_APPS, AFTER the Django app registry is ready. This app
(``infrastructure.persistence.workspaces.workflows``) is installed, so importing
the workflow task modules here is what actually registers them on the worker —
the engine (event_process / run_start / run_step / wait_until / branch /
complete) and the schedule beat task. They cannot be eager-imported in
``api/celery.py`` because those modules import ORM models at module level and
celery.py runs before the registry is ready.
"""

from components.workflow.infrastructure.tasks import (  # noqa: F401
    schedule_tasks,
    workflow_tasks,
)
