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

import re
from fnmatch import fnmatch
from pathlib import Path

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
#     scanning-worker: `-Q cloud_posture,container_security,code_security`
# Only extend this set together with a worker Deployment that consumes the new
# queue — never to make a test pass.
CONSUMED_QUEUES = {"default", "ai_teammate", "cloud_posture", "container_security", "code_security"}

# Queues pinned outside the route table AND outside task decorators, at dynamic
# dispatch sites (grep `queue=`): the scanner registry's per-pillar queue, used
# by dispatch_scan's apply_async(queue=queue_for(source)) in
# components/scanning/application/providers/scanner_registry.py. Kept in
# lockstep with the registry by tests/test_scanner_registration_fitness.py.
# (cloud_posture entered via the Vercel posture entry, #286 — the guard had
# silently missed it, the third live drift these fitness tests caught.)
DISPATCH_PINNED_QUEUES = {"container_security", "code_security", "cloud_posture"}


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


# --- Beat -> effective queue ------------------------------------------------
#
# The three settings modules that define a CELERY_BEAT_SCHEDULE we ship. Read as
# SOURCE (not imported) because prod/dev settings require env vars the suite has
# no business supplying — the same technique, and the same reason, as
# tests/architecture/test_celery_beat_registration.py. That module owns the
# "is it registered / is a tenant bound" half; this one owns "will a worker ever
# pick it up", which is a routing question and so belongs beside CONSUMED_QUEUES.
_BEAT_SETTINGS = ("prod", "dev", "local")

# Matches ``'task': 'some.name'`` at BOTH levels of a fanned-out beat entry:
#
#     "task": "shared_platform.run_for_each_tenant",
#     "kwargs": {"task": "integrations.rediscover_aws_org_accounts"},
#
# The inner name is the one that matters here: run_for_each_tenant re-publishes
# it with ``target.apply_async(kwargs=...)`` and NO queue override, so the
# target's own decorator pin / route decides the queue it lands on.
_BEAT_TASK_RE = re.compile(r"""['"]task['"]\s*:\s*['"]([^'"]+)['"]""")

# tests/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _beat_task_names(settings_name: str) -> set[str]:
    src = (_REPO_ROOT / "api" / "settings" / f"{settings_name}.py").read_text()
    return set(_BEAT_TASK_RE.findall(src))


def _candidate_queues(name: str) -> set[str]:
    """Every queue static config could publish ``name`` to.

    Deliberately a SET rather than a single resolved queue: a task can be both
    decorator-pinned and route-matched, and asserting on every candidate means
    the guard never has to encode Celery's pin-vs-route precedence (which is
    version-detail, and which we would get wrong sooner or later). If any path
    can reach an unconsumed queue, that is the bug.
    """
    queues: set[str] = set()

    task = current_app.tasks.get(name)
    pinned = getattr(task, "queue", None) if task is not None else None
    if pinned:
        queues.add(pinned)

    for pattern, options in TASK_ROUTES.items():
        if fnmatch(name, pattern) and options.get("queue"):
            queues.add(options["queue"])

    return queues or {current_app.conf.task_default_queue}


def test_every_beat_scheduled_task_lands_on_a_consumed_queue():
    """A scheduled task pinned to a queue nobody consumes is a silent black hole.

    The decorator sweep above catches a bad pin only if the task is REGISTERED at
    collection time; it says nothing about whether a given pin is on the hot path
    of a schedule. This one walks the other way — from the beat schedule (both
    levels of the fan-out) to the queue each entry's target actually lands on —
    which is the direction that matters operationally: those are the tasks that
    fire unattended, forever, with nobody watching a return value.

    Confirmed on the live cluster 2026-08-19: the hourly
    ``integrations.rediscover_aws_org_accounts`` entry pinned ``queue="celery"``
    — Celery's stock default name, but this project overrides
    ``task_default_queue`` to ``"default"``, so no deployed worker subscribed to
    it. 25 undelivered messages had piled up in the broker, all of them that one
    task, while the AWS connections they were meant to reconcile kept reading
    CONNECTED in the HUD. Silent coverage loss — the failure a security product
    can least afford.
    """
    # Build the registry exactly as the worker does at boot, so component task
    # modules (which live outside the Django app tree and are NOT autodiscovered)
    # carry their decorator pins here.
    current_app.loader.import_default_modules()
    current_app.finalize()

    violations: list[str] = []
    for settings_name in _BEAT_SETTINGS:
        for name in sorted(_beat_task_names(settings_name)):
            if name.startswith("celery."):
                continue  # built-in canvas primitives
            unconsumed = _candidate_queues(name) - CONSUMED_QUEUES
            if unconsumed:
                violations.append(f"  - {settings_name}.py: {name!r} -> queue(s) {sorted(unconsumed)!r}")

    assert not violations, (
        "These beat-scheduled tasks publish to a queue no deployed k8s worker "
        "consumes — they black-hole in the broker and the scheduled work NEVER "
        "runs, with nothing anywhere saying so:\n"
        + "\n".join(violations)
        + "\n\nFix: drop the queue= pin so the task lands on the project default "
        f"queue ({current_app.conf.task_default_queue!r}), or pin it to a queue a "
        "deployed worker consumes. Note Celery's stock default queue name is "
        "'celery', which this project overrides — queue=\"celery\" is always this bug."
    )
