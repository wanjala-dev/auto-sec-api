"""Celery task shim — delegates to the canonical component module.

This file exists so ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) finds and registers the tasks defined in the components
layer. Follows the same convention as
``infrastructure.persistence.budget.aggregations.tasks``.
"""

from components.agents.infrastructure.tasks.ai_usage_reset_tasks import (  # noqa: F401
    reset_daily_ai_usage_windows,
    reset_monthly_ai_usage_windows,
)
