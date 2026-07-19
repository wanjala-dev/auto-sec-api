"""Load shapes — the canonical profiles. See `.claude/rules/load-testing.md` §4.

Selected via the ``LOAD_PROFILE`` env var. The locustfile imports only the
selected shape (locust 2.x has no ``--shape`` flag and picks one of the
``LoadTestShape`` subclasses present in the locustfile's namespace, so we
constrain the namespace to one).

Run with:

    LOAD_PROFILE=smoke locust --headless -f tests/load/locustfile.py --host=...

Never pass ``--users`` / ``--spawn-rate`` / ``--run-time`` directly; that
bypasses the canonical profiles.
"""
from __future__ import annotations

from locust import LoadTestShape


class SmokeShape(LoadTestShape):
    """1 user, 30s. Post-deploy verify and CI hook.

    Exit code 0 if all assertions pass; exit code 1 if any task fails.
    """

    def tick(self):
        run_time = self.get_run_time()
        if run_time < 30:
            return (1, 1)
        return None


class AvgShape(LoadTestShape):
    """5min ramp 0→50, 30min hold @ 50, 5min ramp 50→0. Steady-state realism."""

    stages = [
        {"duration": 5 * 60, "users": 50, "spawn_rate": 1},
        {"duration": (5 + 30) * 60, "users": 50, "spawn_rate": 1},
        {"duration": (5 + 30 + 5) * 60, "users": 0, "spawn_rate": 5},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


class SpikeShape(LoadTestShape):
    """2min ramp 0→500, 1min hold, 1min ramp 500→0. Burst capacity."""

    stages = [
        {"duration": 2 * 60, "users": 500, "spawn_rate": 5},
        {"duration": (2 + 1) * 60, "users": 500, "spawn_rate": 5},
        {"duration": (2 + 1 + 1) * 60, "users": 0, "spawn_rate": 50},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


class StressShape(LoadTestShape):
    """10min ramp 0→200, 30min hold @ 200, 5min ramp 200→0. Find the breaking point."""

    stages = [
        {"duration": 10 * 60, "users": 200, "spawn_rate": 1},
        {"duration": (10 + 30) * 60, "users": 200, "spawn_rate": 1},
        {"duration": (10 + 30 + 5) * 60, "users": 0, "spawn_rate": 5},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


class SoakShape(LoadTestShape):
    """100 users, 4 hours. Memory leaks, queue drift, pool exhaustion.

    Run from EC2 / CI runner — laptop lid-close kills the run.
    """

    stages = [
        {"duration": 5 * 60, "users": 100, "spawn_rate": 1},
        {"duration": (5 + 4 * 60) * 60, "users": 100, "spawn_rate": 1},
        {"duration": (5 + 4 * 60 + 5) * 60, "users": 0, "spawn_rate": 5},
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


PROFILE_TO_SHAPE = {
    "smoke": SmokeShape,
    "avg": AvgShape,
    "spike": SpikeShape,
    "stress": StressShape,
    "soak": SoakShape,
}
