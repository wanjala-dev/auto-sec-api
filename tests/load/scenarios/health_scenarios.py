"""Unauthenticated health + schema endpoints.

Smoke + load: both. These endpoints have no auth and no DB writes; safe under any shape.
"""
from __future__ import annotations

from locust import task

from tests.load.base_users import AnonymousHttpUser


class HealthLoadUser(AnonymousHttpUser):
    weight = 1

    @task(3)
    def liveness(self) -> None:
        self.client.get("/api/health/", name="/api/health/")

    @task(2)
    def celery_health(self) -> None:
        self.client.get("/api/health/celery/", name="/api/health/celery/")

    @task(1)
    def schema(self) -> None:
        # Schema is large; lower weight to avoid skewing aggregate stats.
        self.client.get("/api/schema/", name="/api/schema/")
