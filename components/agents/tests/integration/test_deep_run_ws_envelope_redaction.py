"""SECURITY CONTRACT — the workspace-scoped ``agent_run`` WS envelope
carries NO run content.

The REST contract (Option A) makes full run detail — prompts (``goal``),
tool inputs/outputs, free-text log messages — OWNER-ONLY via the
``_is_run_owner``-gated ``retrieve``/``events`` endpoints, while
teammates get the redacted progress projection. The realtime signal
bridge publishes to a WORKSPACE-gated channel
(``ResourceStreamConsumer._is_workspace_member``), so its envelope must
meet the same redaction standard: event/status/ids/tool NAMES/numeric
progress — never ``tool_input``/``tool_output``/``message``/``question``
/``error`` or any other free-text payload field.

Mirrors ``TestListProjectionCarriesNoRunContent`` (the REST-side lock)
for the WS publish seam. If this test fails, sensitive run content is
being broadcast to every workspace member.
"""

from __future__ import annotations

import json
import uuid

import pytest

from components.agents.infrastructure.adapters.deep_run_realtime_signal_bridge import (
    DjangoDeepRunRealtimeSignalBridge,
)
from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

# Payload keys that can carry run content — must never appear in the
# published envelope, as keys OR as values.
_SENSITIVE_KEYS = frozenset(
    {
        "goal",
        "tool_input",
        "tool_output",
        "message",
        "question",
        "error",
        "telemetry",
        "system_prompt",
        "user_prompt",
        "llm_response",
    }
)

_SENSITIVE_VALUES = (
    "SECRET INPUT",
    "SECRET OUTPUT",
    "SENSITIVE PROMPT",
    "SECRET QUESTION",
    "SECRET ERROR",
)


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[dict] = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)


def _run(workspace, user):
    return DeepRun.objects.create(
        thread_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        user=user,
        workspace=workspace,
        status=DeepRun.STATUS_RUNNING,
        state={"plan": {"goal": "SENSITIVE PROMPT", "tasks": []}},
    )


@pytest.mark.django_db
class TestWsEnvelopeCarriesNoRunContent:
    def _capture_publish(
        self, monkeypatch, django_capture_on_commit_callbacks, run, *, payload, event_type, tool_name=""
    ):
        """Save a DeepRunLog with *payload* and return the captured publish kwargs."""
        DjangoDeepRunRealtimeSignalBridge.register()
        publisher = _RecordingPublisher()
        monkeypatch.setattr(
            "components.shared_platform.application.providers.realtime_event_provider.get_realtime_event_publisher",
            lambda enabled=True: publisher,
        )
        with django_capture_on_commit_callbacks(execute=True):
            DeepRunLog.objects.create(
                deep_run=run,
                event_type=event_type,
                agent_type="triage_agent",
                tool_name=tool_name,
                status="running",
                payload=payload,
            )
        assert publisher.calls, "bridge published nothing — signal handler not wired?"
        return publisher.calls[-1]

    def test_tool_observation_payload_is_stripped(
        self, monkeypatch, django_capture_on_commit_callbacks, workspace_factory
    ):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)

        call = self._capture_publish(
            monkeypatch,
            django_capture_on_commit_callbacks,
            run,
            event_type="tool_observation",
            tool_name="triage_finding",
            payload={
                "tool_input": "SECRET INPUT",
                "tool_output": "SECRET OUTPUT",
                "truncated_input": False,
                "truncated_output": False,
            },
        )

        blob = json.dumps(call, default=str)
        published_payload = call["payload"]
        assert _SENSITIVE_KEYS.isdisjoint(published_payload.keys())
        for value in _SENSITIVE_VALUES:
            assert value not in blob
        # The redacted progress projection IS present.
        assert published_payload["tool_name"] == "triage_finding"
        assert published_payload["agent_type"] == "triage_agent"
        assert published_payload["deep_run_id"] == run.id
        assert published_payload["thread_id"] == run.thread_id
        assert "log_id" in published_payload
        assert call["resource_id"] == run.plan_id
        assert call["event_name"] == "tool_observation"
        assert call["status"] == "running"

    def test_tool_progress_keeps_numeric_progress_drops_message(
        self, monkeypatch, django_capture_on_commit_callbacks, workspace_factory
    ):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)

        call = self._capture_publish(
            monkeypatch,
            django_capture_on_commit_callbacks,
            run,
            event_type="tool_progress",
            tool_name="retrieve_workspace_context",
            payload={
                "current": 20.0,
                "total": 100.0,
                "progress_percent": 20,
                "severity": "info",
                "message": "Searching workspace knowledge for: 'SENSITIVE PROMPT'",
            },
        )

        blob = json.dumps(call, default=str)
        assert "SENSITIVE PROMPT" not in blob
        assert "message" not in call["payload"]
        # Numeric progress + enum severity survive — teammates SHOULD
        # see progress (Option A), just not content.
        assert call["payload"]["current"] == 20.0
        assert call["payload"]["total"] == 100.0
        assert call["payload"]["progress_percent"] == 20
        assert call["payload"]["severity"] == "info"
        assert call["progress_percent"] == 20

    def test_clarify_and_failure_free_text_is_stripped(
        self, monkeypatch, django_capture_on_commit_callbacks, workspace_factory
    ):
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)

        call = self._capture_publish(
            monkeypatch,
            django_capture_on_commit_callbacks,
            run,
            event_type="run_failed",
            payload={
                "question": "SECRET QUESTION",
                "error": "SECRET ERROR",
                "task_id": "t-1",
            },
        )

        blob = json.dumps(call, default=str)
        assert "SECRET QUESTION" not in blob
        assert "SECRET ERROR" not in blob
        assert call["payload"]["task_id"] == "t-1"

    def test_allowlisted_key_cannot_smuggle_long_text(
        self, monkeypatch, django_capture_on_commit_callbacks, workspace_factory
    ):
        # Defence-in-depth: even an allowed key is dropped when its value
        # is long free text rather than an id/enum/number.
        workspace = workspace_factory()
        run = _run(workspace, workspace.workspace_owner)

        smuggled = "SENSITIVE PROMPT " * 20
        call = self._capture_publish(
            monkeypatch,
            django_capture_on_commit_callbacks,
            run,
            event_type="tool_log",
            payload={"task_id": smuggled, "severity": {"nested": "SECRET INPUT"}},
        )

        blob = json.dumps(call, default=str)
        assert "SENSITIVE PROMPT" not in blob
        assert "SECRET INPUT" not in blob
        assert "task_id" not in call["payload"]
        assert "severity" not in call["payload"]
