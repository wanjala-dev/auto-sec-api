"""
Base Celery task that retries transient database issues by default.

This is the global default task base for all Celery tasks in the project.
It handles OperationalError and InterfaceError (connection churn in
long-lived worker processes) with exponential backoff.
"""

from celery import Task
from django.db.utils import InterfaceError, OperationalError


class DatabaseSafeTask(Task):
    """Base Celery task that retries transient database issues by default."""

    autoretry_for = (OperationalError, InterfaceError)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    default_retry_delay = 60
    max_retries = 3
