"""Tests for the isolated detector runner."""

from __future__ import annotations

import time

from components.agents.application.services.detector_runner import (
    run_all_detectors,
    run_detector_isolated,
)


class _FakeContext:
    pass


class _FakeDetector:
    def __init__(self, slug="test_detector", *, should_run=True, signals=None, results=None, raise_on_execute=None, sleep_seconds=0):
        self.slug = slug
        self._should_run = should_run
        self._signals = signals or []
        self._results = results or []
        self._raise_on_execute = raise_on_execute
        self._sleep = sleep_seconds

    def should_run(self, context):
        return self._should_run

    def gather_signals(self, context):
        return self._signals

    def execute(self, context):
        if self._sleep:
            time.sleep(self._sleep)
        if self._raise_on_execute:
            raise self._raise_on_execute
        return self._results


class _FakeResult:
    def __init__(self, action_type="test", title="Test"):
        self.action_type = action_type
        self.title = title
        self.summary = ""
        self.payload = {}
        self.context = {}
        self.status = "pending"
        self.detector_slug = ""
        self.agent_type = ""
        self.auto_execute = False
        self.metadata = {}
        self.actor_type = "ai"
        self.actor_id = ""


class TestRunDetectorIsolated:
    def test_successful_detector(self):
        detector = _FakeDetector(results=[_FakeResult()])
        result = run_detector_isolated(detector, _FakeContext())

        assert result.slug == "test_detector"
        assert not result.skipped
        assert not result.error
        assert len(result.results) == 1
        assert result.duration_ms >= 0

    def test_skipped_detector(self):
        detector = _FakeDetector(should_run=False)
        result = run_detector_isolated(detector, _FakeContext())

        assert result.skipped
        assert "should_run" in result.skip_reason

    def test_detector_execution_error_is_contained(self):
        detector = _FakeDetector(raise_on_execute=RuntimeError("boom"))
        result = run_detector_isolated(detector, _FakeContext())

        assert result.error == "boom"
        assert not result.skipped  # error ≠ skipped

    def test_detector_timeout(self):
        detector = _FakeDetector(sleep_seconds=5)
        result = run_detector_isolated(detector, _FakeContext(), timeout_seconds=0.1)

        assert result.skipped
        assert "timeout" in result.skip_reason.lower() or "Timed out" in result.error

    def test_should_run_exception_is_contained(self):
        class _BadShouldRun:
            slug = "bad"
            def should_run(self, ctx):
                raise ValueError("config error")

        result = run_detector_isolated(_BadShouldRun(), _FakeContext())
        assert result.skipped
        assert "config error" in result.error


class TestRunAllDetectors:
    def test_runs_multiple_detectors(self):
        detectors = [
            _FakeDetector(slug="d1", results=[_FakeResult()]),
            _FakeDetector(slug="d2", results=[_FakeResult(), _FakeResult()]),
        ]
        results = run_all_detectors(detectors, _FakeContext())

        assert len(results) == 2
        assert results[0].slug == "d1"
        assert len(results[0].results) == 1
        assert results[1].slug == "d2"
        assert len(results[1].results) == 2

    def test_one_failure_does_not_affect_others(self):
        detectors = [
            _FakeDetector(slug="good", results=[_FakeResult()]),
            _FakeDetector(slug="bad", raise_on_execute=RuntimeError("fail")),
            _FakeDetector(slug="also_good", results=[_FakeResult()]),
        ]
        results = run_all_detectors(detectors, _FakeContext())

        assert len(results) == 3
        assert not results[0].error
        assert results[1].error == "fail"
        assert not results[2].error

    def test_timeout_does_not_affect_others(self):
        detectors = [
            _FakeDetector(slug="fast", results=[_FakeResult()]),
            _FakeDetector(slug="slow", sleep_seconds=5),
        ]
        results = run_all_detectors(detectors, _FakeContext(), timeout_per_detector=0.1)

        assert len(results) == 2
        assert not results[0].error
        assert results[1].error or results[1].skipped
