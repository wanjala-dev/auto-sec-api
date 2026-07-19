"""Unit test: ``report_at_risk_projects`` emits ``ProjectAtRiskFindingsDetected``.

Phase 5a (N=3) of the Agents-as-Teammates migration replaced the
``AIActionService.log_action`` loop inside the at-risk detector with a
single domain-event emission. The specialist handler subscribes.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from components.project.domain.events.project_at_risk_findings_detected_event import (
    ProjectAtRiskFindingsDetected,
)
from components.project.infrastructure.services.at_risk_detector_service import (
    ProjectAtRiskFinding,
)


@pytest.fixture
def fake_workspace():
    return SimpleNamespace(id="ws-aaa-bbb-ccc", workspace_name="Demo")


def _captured_events_from(publish_mock):
    return [
        call.args[0] if call.args else call.kwargs["event"]
        for call in publish_mock.call_args_list
    ]


@patch(
    "components.project.infrastructure.services.at_risk_detector_service."
    "detect_at_risk_projects"
)
def test_emits_one_event_with_all_findings(detect_mock, fake_workspace):
    from components.project.infrastructure.services.at_risk_detector_service import (
        report_at_risk_projects,
    )

    detect_mock.return_value = [
        ProjectAtRiskFinding(
            project_id="proj-1",
            project_title="Build Greenhouse",
            team_title="Operations",
            overdue_task_count=4,
            period="2026-06",
        ),
        ProjectAtRiskFinding(
            project_id="proj-2",
            project_title="Sponsor Onboarding",
            team_title="Programs",
            overdue_task_count=12,
            period="2026-06",
        ),
    ]

    with patch(
        "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
        "CeleryEventPublisher.publish"
    ) as publish_mock:
        count = report_at_risk_projects(fake_workspace)

    assert count == 2
    events = _captured_events_from(publish_mock)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ProjectAtRiskFindingsDetected)
    assert event.workspace_id == fake_workspace.id
    assert event.detector_key == "project_overdue_task_backlog"
    assert event.period == "2026-06"
    assert len(event.findings) == 2
    big = next(f for f in event.findings if f["project_id"] == "proj-2")
    assert big["overdue_task_count"] == 12
    assert big["impact_score"] == 90  # >= 10 overdue


@patch(
    "components.project.infrastructure.services.at_risk_detector_service."
    "detect_at_risk_projects"
)
def test_no_findings_publishes_no_event(detect_mock, fake_workspace):
    from components.project.infrastructure.services.at_risk_detector_service import (
        report_at_risk_projects,
    )

    detect_mock.return_value = []

    with patch(
        "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
        "CeleryEventPublisher.publish"
    ) as publish_mock:
        count = report_at_risk_projects(fake_workspace)

    assert count == 0
    publish_mock.assert_not_called()


@patch(
    "components.project.infrastructure.services.at_risk_detector_service."
    "detect_at_risk_projects"
)
def test_impact_score_buckets(detect_mock, fake_workspace):
    from components.project.infrastructure.services.at_risk_detector_service import (
        report_at_risk_projects,
    )

    detect_mock.return_value = [
        ProjectAtRiskFinding(
            project_id="p3", project_title="3 overdue",
            team_title="", overdue_task_count=3, period="2026-06",
        ),
        ProjectAtRiskFinding(
            project_id="p5", project_title="5 overdue",
            team_title="", overdue_task_count=5, period="2026-06",
        ),
        ProjectAtRiskFinding(
            project_id="p10", project_title="10 overdue",
            team_title="", overdue_task_count=10, period="2026-06",
        ),
    ]

    with patch(
        "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
        "CeleryEventPublisher.publish"
    ) as publish_mock:
        report_at_risk_projects(fake_workspace)

    event = _captured_events_from(publish_mock)[0]
    by_id = {f["project_id"]: f for f in event.findings}
    assert by_id["p3"]["impact_score"] == 50
    assert by_id["p5"]["impact_score"] == 70
    assert by_id["p10"]["impact_score"] == 90
