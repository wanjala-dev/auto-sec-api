"""Published seam for the shared background-job progress reporter.

``job_progress`` is the canonical primitive for reporting a long-running task's
live progress (BackgroundJob row + WS publish). Other contexts' Celery tasks (the
cloud_posture scan) drive it through this application-layer re-export instead of
importing ``shared_platform.infrastructure.services.job_progress`` directly —
cross-context infrastructure imports are forbidden (ADR 0004 infra-boundary series).
"""

from __future__ import annotations

from components.shared_platform.infrastructure.services.job_progress import (
    complete_job,
    fail_job,
    start_job,
    update_job,
)

__all__ = ["complete_job", "fail_job", "start_job", "update_job"]
