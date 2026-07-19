"""Beat entry point: fire due recurring workflow schedules.

Thin primary adapter — the scheduler is the external trigger. It captures
``now`` (so the application layer stays free of Django's timezone import) and
delegates to ``WorkflowService.fire_due_schedules``.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="workflow.run_due_schedules", bind=True, max_retries=0)
def run_due_schedules(self) -> dict:
    from components.workflow.application.service import WorkflowService

    result = WorkflowService().fire_due_schedules(timezone.now())
    return result
