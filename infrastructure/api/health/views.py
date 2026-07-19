"""Health endpoints for ops / alerting.

Two endpoints, doing two different jobs:

* ``GET /api/health/`` — **liveness**. Cheap, no I/O, always 200 if the WSGI
  process is up and the URLConf imported. Wire CloudFront / load-balancer
  health checks and uptime monitors here. It deliberately does NOT touch the
  database, Redis, or Celery — those are dependencies, and a liveness probe
  that turns red on a Redis hiccup will restart healthy web pods and make a
  small problem big.

* ``GET /api/health/celery/`` — **readiness for the queue**. Reaches out to
  the broker, returns worker count + backlog, and flips to 503 when the
  backlog crosses the critical threshold. Use this for Celery-specific
  alerting, not for whether the API is "up".

Inspector calls have a small but non-zero broker round-trip; the timeout is
deliberately tight so a slow Redis can't make the health check itself a
liability. A timeout returns ``unknown`` rather than a 5xx — workers may still
be fine and we don't want to false-alert on broker hiccups.
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.celery import app as celery_app


logger = logging.getLogger(__name__)


# Reserved-tasks backlog thresholds. Tune by observing typical depth in prod.
WARN_THRESHOLD = 100
CRITICAL_THRESHOLD = 500


class LivenessView(APIView):
    """GET /api/health/ — process is up and the URLConf imported. No I/O."""

    permission_classes = (AllowAny,)
    authentication_classes: tuple[Any, ...] = ()

    def get(self, request: Any) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class CeleryHealthView(APIView):
    """GET /api/health/celery/ — worker count + queue depth, with status."""

    permission_classes = (AllowAny,)
    authentication_classes: tuple[Any, ...] = ()

    def get(self, request: Any) -> Response:
        try:
            inspector = celery_app.control.inspect(timeout=1.0)
            active = inspector.active() or {}
            reserved = inspector.reserved() or {}
        except Exception:  # noqa: BLE001 - any broker hiccup → "unknown", not 500
            logger.exception("celery_health: inspector call failed")
            return Response(
                {
                    "status": "unknown",
                    "detail": "celery inspector unreachable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        worker_count = len(active)
        active_count = sum(len(tasks) for tasks in active.values())
        reserved_count = sum(len(tasks) for tasks in reserved.values())

        if worker_count == 0:
            level, http_status = "critical", status.HTTP_503_SERVICE_UNAVAILABLE
            detail = "no workers responding"
        elif reserved_count >= CRITICAL_THRESHOLD:
            level, http_status = "critical", status.HTTP_503_SERVICE_UNAVAILABLE
            detail = f"queue backlog {reserved_count} >= {CRITICAL_THRESHOLD}"
        elif reserved_count >= WARN_THRESHOLD:
            level, http_status = "warning", status.HTTP_200_OK
            detail = f"queue backlog {reserved_count} >= {WARN_THRESHOLD}"
        else:
            level, http_status = "healthy", status.HTTP_200_OK
            detail = "ok"

        return Response(
            {
                "status": level,
                "detail": detail,
                "workers": worker_count,
                "active_tasks": active_count,
                "reserved_tasks": reserved_count,
                "thresholds": {
                    "warn": WARN_THRESHOLD,
                    "critical": CRITICAL_THRESHOLD,
                },
            },
            status=http_status,
        )
