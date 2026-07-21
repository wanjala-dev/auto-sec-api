"""Contract: every Celery Beat schedule entry names a registered task.

This guard catches the failure mode where Beat dispatches a task name the
worker never registered. The worker then logs ``Received unregistered task
of type '<name>'`` every time the entry fires, and the scheduled work
silently never runs.

There are two ways a beat name ends up unregistered, both caught here:

1. **Module never imported (class A).** Component task modules live under
   ``components/<ctx>/...`` — OUTSIDE the Django app tree — so Celery's
   ``autodiscover_tasks()`` (which only scans ``<app>/tasks.py`` for each
   ``INSTALLED_APPS`` entry) does NOT find them. They must be imported
   explicitly in ``api/celery.py``. Forget that import and the task is
   registered nowhere, even though its ``name=`` matches the beat entry.

2. **Beat name drift (class B).** The task IS registered (via an explicit
   import or a ``infrastructure/persistence/<app>/tasks.py`` autodiscover
   shim) but under a different string than the beat schedule dispatches —
   e.g. beat says ``budget.tasks.compute_budget_history_for_all_workspaces``
   while ``@shared_task(name=...)`` declares ``compute_budget_history_for_all_workspaces``.

Both classes shipped silently to prod once (2026-06-20) — five beat
entries erroring on every fire, invisible to every stubbed test. See the
``celery-tasks`` skill §13 for the prevention rule this test enforces.

This is a pure static + import check — it reads the beat ``task`` strings
out of the settings source files (no need to import prod/dev settings,
which require env vars) and compares them against the live task registry
that ``api.celery`` builds. No DB access.
"""
from __future__ import annotations

import re
from pathlib import Path

from api.celery import app

# The three settings modules that define a CELERY_BEAT_SCHEDULE we ship.
_SETTINGS = ("prod", "dev", "local")

# Matches ``'task': 'some.name'`` / ``"task": "some.name"`` beat entries.
_TASK_RE = re.compile(r"""['"]task['"]\s*:\s*['"]([^'"]+)['"]""")

# tests/architecture/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _registered_task_names() -> set[str]:
    """Build the task registry exactly as the worker does at boot.

    Importing ``api.celery`` runs the explicit component-task imports at the
    bottom of that module (class-A registration). ``import_default_modules``
    + ``finalize`` then runs autodiscover over INSTALLED_APPS so the
    persistence-app ``tasks.py`` shims register too.
    """
    app.loader.import_default_modules()
    app.finalize()
    return set(app.tasks.keys())


def _beat_task_names(settings_name: str) -> list[str]:
    src = (_REPO_ROOT / "api" / "settings" / f"{settings_name}.py").read_text()
    return sorted(set(_TASK_RE.findall(src)))


def test_every_beat_task_is_registered():
    registered = _registered_task_names()
    failures: list[str] = []
    for settings_name in _SETTINGS:
        for name in _beat_task_names(settings_name):
            if name.startswith("celery."):
                continue  # built-in canvas primitives
            if name not in registered:
                failures.append(
                    f"{settings_name}.py: beat task '{name}' is not a registered Celery task"
                )

    assert not failures, (
        "CELERY_BEAT_SCHEDULE references unregistered task(s) — the worker "
        "will log 'Received unregistered task' on every fire and the work "
        "never runs:\n  - "
        + "\n  - ".join(failures)
        + "\n\nFix: (class A) import the task's module in api/celery.py — "
        "component task modules outside the Django app tree are NOT "
        "autodiscovered; or (class B) make the beat 'task' string match the "
        "@shared_task(name=...) value. See the celery-tasks skill §13."
    )


# Wanjala-fork leftovers that used to fire from beat (or the persisted
# celerybeat-schedule shelve) with no registered task behind them. The
# recommendations projection sweep crashed with an ImportError on every fire
# until its beat entry was pruned; this pins the removal so the entry (and the
# task) can never quietly return without the backing context being ported too.
_REMOVED_WANJALA_TASKS = (
    "recommendations.refresh_recommendable_items",
)


def test_removed_wanjala_leftover_tasks_stay_gone():
    registered = _registered_task_names()
    for name in _REMOVED_WANJALA_TASKS:
        assert name not in registered, (
            f"'{name}' is registered again — the wanjala surface behind it was "
            "removed from this fork; port the whole context or drop the task."
        )
        for settings_name in _SETTINGS:
            assert name not in _beat_task_names(settings_name), (
                f"{settings_name}.py schedules removed wanjala task '{name}'"
            )
