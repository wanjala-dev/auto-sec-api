"""Canonical Celery task->queue route table — the SSOT every settings module imports.

NAMESPACE GOTCHA (why this file exists): ``api/celery.py`` configures Celery with
``app.config_from_object("django.conf:settings", namespace="CELERY")``. Under a
namespace, Celery only maps NEW-style setting names — ``CELERY_TASK_ROUTES`` ->
``task_routes``. The old-style ``CELERY_ROUTES`` strips to ``routes``, which is
not a Celery setting, and is **silently ignored**. Verified empirically on
Celery 5.4.0 in the app image: with ``CELERY_ROUTES`` set, ``app.conf.task_routes``
was ``None`` at runtime, so every "routed" task actually ran on the default
queue. The same trap applies to ``CELERY_QUEUES`` (-> ignored) and
``CELERY_DEFAULT_QUEUE`` (-> ignored; the default queue silently stayed Celery's
built-in ``"celery"``). Always use the ``CELERY_TASK_*`` new-style names.

INVARIANT: every queue named here (or pinned via ``queue=`` at a task decorator /
dispatch site) MUST be consumed by a deployed worker, or its tasks black-hole in
the broker forever. The deployed consumers (auto-sec-infra ``k8s/bases``):

- ``celery-worker``            — no ``-Q`` -> the default queue (``default``)
- ``celery-ai-teammate-worker``— ``-Q ai_teammate``
- ``scanning-worker``          — ``-Q cloud_posture,container_security``

``tests/test_celery_task_routes.py`` locks both halves: the setting must apply
at runtime, and every routed/pinned queue must be in the consumed set.

The scan pillars (``cloud_posture``, ``container_security``) are deliberately NOT
routed here — they pin their queue at the task decorator / ``dispatch_scan``
(dynamic per source), which is the working per-pillar isolation pattern.
"""

QUEUE_DEFAULT = "default"
QUEUE_AI_TEAMMATE = "ai_teammate"

TASK_ROUTES = {
    # The whole AI-teammate task family — the beat fan-out
    # (schedule_ai_teammate_runs), the per-workspace detector cycle
    # (run_ai_teammate_cycle), specialist dispatch, agent executions, and the
    # deep-run tasks (those two also pin queue= at their decorators; same
    # queue, no conflict) — runs on the dedicated ai-teammate worker. That
    # deployment is sized for it (1Gi) and carries the base AWS credentials the
    # detector cycle's boto3 cloud-graph sync needs; the 768Mi default worker
    # has neither.
    "infrastructure.ai.agents.tasks.*": {"queue": QUEUE_AI_TEAMMATE},
    # Embedding jobs are heavy model/API work — keep them off the default
    # queue so they can't starve the light platform tasks.
    "infrastructure.ai.embeddings.tasks.*": {"queue": QUEUE_AI_TEAMMATE},
}
