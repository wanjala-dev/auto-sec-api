import logging
from smtplib import SMTPException

from celery import shared_task
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from components.shared_kernel.domain.circuit_breaker import circuit_breaker_registry

logger = logging.getLogger(__name__)

_SES_BREAKER_SLUG = "ses_email"


@shared_task(
    name="send_email_task",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def send_email_task(
    self,
    to_email,
    from_email,
    subject,
    text_content,
    html_template,
    contact_data,
    idempotency_key=None,
):
    """Send the contact-form email.

    celery-tasks skill §3:
    - §3a: only retry transient SMTP/SES faults; a missing template or a
      programming error fails fast instead of burning 5 backed-off retries.
    - §2 (idempotency): under acks_late a worker can redeliver after a send
      that already succeeded — an ``idempotency_key`` + cache guard stops the
      duplicate email.
    - §3c: render BEFORE building the connection; the per-attempt SMTP socket
      timeout comes from ``EMAIL_TIMEOUT`` (settings) reinforced by an explicit
      ``get_connection(timeout=10)``.
    - §3e: gate on the shared "ses_email" circuit breaker so a sustained SES
      outage fails fast instead of every queued contact email retrying into it.
    """
    logger.info("send_email_task started task_id=%s", self.request.id)

    cache_key = f"contact_email_sent:{idempotency_key}" if idempotency_key else None
    if cache_key and not cache.add(cache_key, "1", timeout=86400):
        logger.info("send_email_task skip duplicate key=%s", idempotency_key)
        return

    # Render first — a TemplateDoesNotExist is a deploy/config bug, never
    # transient. Fail fast (and release the idempotency reservation).
    try:
        html_content = render_to_string(html_template, contact_data)
    except TemplateDoesNotExist:
        if cache_key:
            cache.delete(cache_key)
        logger.exception("send_email_task non-retryable template error template=%s", html_template)
        raise

    breaker = circuit_breaker_registry.get(_SES_BREAKER_SLUG)
    if not breaker.allow_request():
        # SES is sustained-down. Release the reservation and back off — don't
        # pile another send onto a struggling provider.
        if cache_key:
            cache.delete(cache_key)
        logger.warning("send_email_task circuit open task_id=%s; deferring", self.request.id)
        raise self.retry(countdown=60)

    connection = get_connection(timeout=10)
    email = EmailMessage(
        subject,
        body=html_content,
        from_email=from_email,
        to=[to_email],
        connection=connection,
    )
    email.content_subtype = "html"
    try:
        email.send()
        breaker.record_success()
        logger.info("send_email_task completed task_id=%s", self.request.id)
    except SMTPException as exc:
        breaker.record_failure()
        if cache_key:
            cache.delete(cache_key)  # let the retry re-attempt the send
        logger.exception("send_email_task transient send failure task_id=%s", self.request.id)
        raise self.retry(exc=exc) from exc
