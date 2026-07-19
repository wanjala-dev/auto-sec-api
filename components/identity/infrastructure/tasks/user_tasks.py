"""Async tasks for user-related side effects."""

from celery import shared_task

from components.identity.infrastructure.adapters.security import record_security_event


@shared_task(
    name="infrastructure.users.tasks.notify_security_event",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def notify_security_event(self, *, actor_id, user_id, verb, event_code, metadata):
    """Record security events in the background."""
    record_security_event(
        actor_id=actor_id,
        user_id=user_id,
        verb=verb,
        event_code=event_code,
        metadata=metadata,
    )
