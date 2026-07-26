"""Published seam for triggering a scan (ADR 0006).

Other contexts (container_security, cloud_posture) trigger scans through this
application-layer provider rather than importing the scanning-context Celery task
module directly — cross-context infrastructure imports are forbidden. ``dispatch_scan``
enqueues the async ``scanning.run_scan`` task onto the pillar's queue; ``run_scan``
runs it inline (ops/tests).
"""

from __future__ import annotations

from typing import Any


def dispatch_scan(**kwargs: Any) -> Any:
    """Enqueue a scan; returns the Celery AsyncResult."""
    from components.scanning.infrastructure.tasks.scan_tasks import dispatch_scan as _dispatch

    return _dispatch(**kwargs)


def run_scan(**kwargs: Any) -> Any:
    """Run a scan inline (synchronous) — for ops/tests."""
    from components.scanning.infrastructure.tasks.scan_tasks import run_scan as _run

    return _run(**kwargs)
