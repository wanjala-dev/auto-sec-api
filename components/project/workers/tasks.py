"""Celery Beat entry points for the project bounded context.

Beat-scheduled tasks are PRIMARY ADAPTERS — the scheduler is an external
trigger driving the application, just like an HTTP request or CLI command.
Each function should be a thin wrapper that delegates to an application
service or use case.

To activate:
1. Register this module in CELERY_IMPORTS or add `@shared_task` decorators.
2. Add entries to CELERY_BEAT_SCHEDULE in api/settings/local.py.
"""
