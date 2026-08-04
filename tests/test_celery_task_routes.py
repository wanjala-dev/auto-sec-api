"""Lock the Celery routing config (regression guard for the inert-route-table bug).

Two invariants, one per failure mode:

1. **The setting must actually apply.** ``api/celery.py`` uses
   ``config_from_object("django.conf:settings", namespace="CELERY")``, under
   which only NEW-style names map — ``CELERY_TASK_ROUTES`` -> ``task_routes``.
   The old ``CELERY_ROUTES`` name was silently ignored (verified on Celery
   5.4.0: ``task_routes`` was ``None`` at runtime), so every "routed" task ran
   on the default queue. If someone renames the setting back, the assertion on
   ``current_app.conf.task_routes`` fails.

2. **Every routed/pinned queue must have a deployed consumer.** A route to a
   queue no worker consumes is a silent task black hole in the broker. The
   consumed set below is the ground truth from the auto-sec-infra worker
   Deployments — adding a route to a new queue must ship WITH a worker that
   consumes it (and an update to this list).
"""

from __future__ import annotations

from celery import current_app
from django.conf import settings

from infrastructure.celery.routes import TASK_ROUTES

# Queues a deployed worker actually consumes — ground truth is the worker args
# in auto-sec-infra:
#   k8s/bases/celery/deployments.yaml
#     celery-worker: `celery -A api worker` with no -Q -> the default queue
#     celery-ai-teammate-worker: /start-celeryworker-ai-teammate
#       (docker/scripts/celery/start-ai-teammate.sh) -> `-Q ai_teammate`
#   k8s/bases/scanning/scanning-worker.yaml
#     scanning-worker: `-Q cloud_posture,container_security`
# Only extend this set together with a worker Deployment that consumes the new
# queue — never to make a test pass.
CONSUMED_QUEUES = {"default", "ai_teammate", "cloud_posture", "container_security"}

# Queues pinned outside the route table AND outside task decorators, at dynamic
# dispatch sites (grep `queue=`): the scanner registry's per-pillar queue, used
# by dispatch_scan's apply_async(queue=queue_for(source)) in
# components/scanning/application/providers/scanner_registry.py. (cloud_posture
# is decorator-pinned and covered by the registered-task sweep below.)
DISPATCH_PINNED_QUEUES = {"container_security"}


def test_task_routes_setting_actually_applies():
    """CELERY_TASK_ROUTES must survive the namespace mapping into app.conf."""
    assert settings.CELERY_TASK_ROUTES == TASK_ROUTES
    assert current_app.conf.task_routes, (
        "app.conf.task_routes is empty — the routes setting regressed to a name "
        "config_from_object(namespace='CELERY') ignores (e.g. old-style CELERY_ROUTES)."
    )
    assert current_app.conf.task_routes == TASK_ROUTES


def test_default_queue_is_named_default():
    """CELERY_TASK_DEFAULT_QUEUE must apply (old CELERY_DEFAULT_QUEUE was ignored,
    silently leaving the default queue named "celery" while every comment and the
    k8s celery-worker docs said "default")."""
    assert current_app.conf.task_default_queue == "default"


def test_every_routed_queue_is_consumed_by_a_deployed_worker():
    for pattern, options in TASK_ROUTES.items():
        queue = options.get("queue")
        assert queue in CONSUMED_QUEUES, (
            f"Route {pattern!r} targets queue {queue!r}, which no deployed k8s "
            "worker consumes — its tasks would black-hole in the broker. Ship a "
            "consuming worker (and update CONSUMED_QUEUES) or route elsewhere."
        )


def test_every_decorator_pinned_queue_is_consumed_by_a_deployed_worker():
    """Sweep every registered task's decorator-pinned queue against the consumed set."""
    pinned = {name: task.queue for name, task in current_app.tasks.items() if getattr(task, "queue", None)}
    assert pinned, "expected at least the deep-run / scan tasks to pin a queue"
    for name, queue in pinned.items():
        assert queue in CONSUMED_QUEUES, (
            f"Task {name!r} pins queue={queue!r}, which no deployed k8s worker "
            "consumes — it would black-hole in the broker."
        )


def test_dispatch_pinned_queues_are_consumed_by_a_deployed_worker():
    assert DISPATCH_PINNED_QUEUES <= CONSUMED_QUEUES
