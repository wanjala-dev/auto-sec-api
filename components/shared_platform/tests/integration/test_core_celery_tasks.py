"""Tests for shared Celery task bases and helpers."""

from __future__ import annotations

import pytest

import httpx
from requests.exceptions import RequestException

from components.shared_platform.infrastructure.services.celery_tasks import ExternalServiceRetryTask, shared_task_with_external_retry


@pytest.mark.parametrize(
    "expected_exc",
    [
        ConnectionError,
        TimeoutError,
        RequestException,
        httpx.RequestError,
    ],
)
def test_external_service_retry_task_covers_transient_io_exceptions(expected_exc):
    """External retry policy includes common transient/network exceptions."""
    assert expected_exc in ExternalServiceRetryTask.autoretry_for


def test_shared_task_with_external_retry_requires_explicit_name():
    """Tasks must declare an explicit Celery name for stability."""
    with pytest.raises(ValueError, match="requires an explicit name"):
        shared_task_with_external_retry()


def test_shared_task_with_external_retry_sets_base_task():
    """Helper attaches the ExternalServiceRetryTask base to the generated task class."""

    @shared_task_with_external_retry(name="core.tests.external_retry_task")
    def example_task():
        return "ok"

    task_obj = example_task._get_current_object()
    assert issubclass(task_obj.__class__, ExternalServiceRetryTask)
