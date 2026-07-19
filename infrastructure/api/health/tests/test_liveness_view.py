"""Tests for ``GET /api/health/`` — the cheap liveness probe.

The endpoint exists so CloudFront / load balancers / uptime monitors have
a route they can hit without authenticating, without touching the
database, and without paying broker latency. The Celery health endpoint
already exists for queue-specific alerting; this one answers the simpler
question "is the WSGI process up and the URLConf importable?"

If a future change accidentally couples this endpoint to the DB or
Redis, these tests catch it — the whole point is that liveness must
keep returning 200 even when downstream dependencies wobble.
"""
from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.unit
class TestLivenessEndpoint:
    def test_returns_200_with_status_ok(self):
        response = APIClient().get("/api/health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}

    def test_does_not_require_authentication(self):
        # Unauthenticated client. If a permission class change ever
        # locks this down, uptime monitors start false-paging.
        response = APIClient().get("/api/health/")
        assert response.status_code == status.HTTP_200_OK

    def test_distinct_from_celery_health(self):
        # Sanity: the two routes resolve to different views and don't
        # accidentally share the same handler.
        liveness = APIClient().get("/api/health/")
        celery = APIClient().get("/api/health/celery/")
        # Both should respond, but with different payload shapes.
        # Liveness is flat ``{"status": "ok"}``; celery returns workers/active_tasks.
        assert "workers" not in liveness.json()
        assert liveness.json() == {"status": "ok"}
        # Celery health may be 200 or 503 depending on broker state in
        # the test env — we don't assert on its body here, only that it
        # exists and isn't the same as liveness.
        assert celery.status_code in (
            status.HTTP_200_OK,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
