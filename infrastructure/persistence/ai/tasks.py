"""Celery task shim — delegates to canonical component module.

This file exists so that ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) can find and register the tasks defined in the
components layer.
"""

from components.agents.infrastructure.tasks.agent_tasks import (  # noqa: F401
    dispatch_finding_specialist,
    run_agent_execution,
    run_ai_teammate_cycle,
    schedule_ai_teammate_runs,
)
