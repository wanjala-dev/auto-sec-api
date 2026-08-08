"""Architecture guardrail: a test that READS a post-commit side effect must
execute the on-commit callbacks — otherwise it passes vacuously.

The trap (hit for real on 2026-08-08, task #114): ``NotificationDispatcher``
enqueues its per-recipient work inside ``transaction.on_commit``. A
``pytest.mark.django_db`` test runs in a transaction that is ROLLED BACK and
never commits, so those callbacks never fire. A test that triggers a dispatch
and then asserts::

    assert Notification.objects.filter(recipient=target).exists()

fails for the right reason today — but the inverse assertion::

    assert not Notification.objects.filter(recipient=target).exists()

passes for entirely the WRONG reason: nothing was ever going to be created in
that transaction, so the assertion is vacuous and would keep passing even if
the notification logic were deleted outright.

The fix is pytest-django's ``django_capture_on_commit_callbacks(execute=True)``
fixture, which runs the registered callbacks (Celery is eager under test
settings, so the whole chain then executes inline).

THE RULE
--------
A test module that makes a READ assertion against ``Notification.objects``
(``.filter`` / ``.get`` / ``.count`` / ``.exists``) must either:

  1. use ``django_capture_on_commit_callbacks`` — it drives the real funnel; or
  2. invoke the delivery/dispatch task DIRECTLY (``.apply(``/``.apply_async(``)
     — a synchronous call that needs no commit; or
  3. create its rows directly with ``Notification.objects.create(...)`` — it is
     testing a read/API surface, not the dispatch pipeline.

Anything else is asserting on a pipeline it never actually ran.

Scope note: this guards the notification funnel specifically, because that is
the post-commit path most often asserted against. Other deferred side effects
(``job_progress``'s realtime publish, the payments event emit) are either
tested through their task entry point or explicitly document that they assert
the durable DB row instead — see ``components/shared_platform/tests/
integration/test_job_progress.py``'s module docstring for the pattern to
follow when a post-commit effect is deliberately out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# A READ of the notification table — the assertion shape that can go vacuous.
_READ_PATTERN = re.compile(r"Notification\.objects\.(filter|get|count|exists|all)\b")
# Rows the test created itself — it owns the state, no pipeline involved.
_DIRECT_CREATE = "Notification.objects.create"
# Synchronous task invocation — runs inline, no commit needed.
_DIRECT_TASK_CALL = re.compile(r"\.(apply|apply_async)\(")
_CAPTURE_FIXTURE = "django_capture_on_commit_callbacks"


def _test_modules() -> list[Path]:
    return sorted(COMPONENTS_DIR.rglob("test_*.py"))


def test_notification_read_assertions_execute_on_commit_callbacks() -> None:
    """Every test reading Notification rows must actually run the pipeline."""
    violations: list[str] = []

    for path in _test_modules():
        source = path.read_text(encoding="utf-8")

        if not _READ_PATTERN.search(source):
            continue
        if _CAPTURE_FIXTURE in source:
            continue
        if _DIRECT_TASK_CALL.search(source):
            continue
        if _DIRECT_CREATE in source:
            continue

        violations.append(
            f"  - {path.relative_to(ROOT)} asserts on Notification.objects without "
            f"executing on-commit callbacks, invoking the task directly, or creating "
            f"the rows itself. The dispatch funnel defers to transaction.on_commit, "
            f"which never fires inside a django_db test — this assertion is vacuous."
        )

    assert not violations, (
        "Vacuous post-commit assertions found. Wrap the triggering call in "
        "`django_capture_on_commit_callbacks(execute=True)` (Celery is eager under "
        "test settings, so the full chain then runs inline):\n" + "\n".join(violations)
    )
