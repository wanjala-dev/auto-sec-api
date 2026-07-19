"""Unit tests — patch-path derivation + patch groundedness (no DB, no LLM).

The LLM boundary is a scripted fake port (``chat`` returns a canned
response object); groundedness and path derivation are deterministic.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from components.integrations.application.log_patch_advisor_service import (
    LogPatchAdvisor,
    derive_candidate_path,
)


class _FakeLlm:
    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return SimpleNamespace(content=self._content)


def _payload(message: str, evidence_detail: str = "", suggested_fix: str = "") -> dict:
    return {
        "service": "celery_worker",
        "level": "ERROR",
        "message": message,
        "signal": "ERROR in celery_worker",
        "evidence": [{"type": "log_line", "detail": evidence_detail or message}],
        "suggested_fix": suggested_fix,
    }


@pytest.mark.unit
class TestDeriveCandidatePath:
    def test_traceback_file_frame_wins(self):
        payload = _payload(
            "boom",
            evidence_detail=(
                "Traceback (most recent call last):\n"
                '  File "/app/manage.py", line 10, in main\n'
                '  File "/app/components/workflow/application/service.py", line 42, in run\n'
                "ImportError: cannot import name 'run_due_schedules'"
            ),
        )
        # Deepest (last) frame wins — that's where the error raised.
        assert derive_candidate_path(payload) == "components/workflow/application/service.py"

    def test_traceback_without_app_prefix(self):
        payload = _payload("x", evidence_detail='File "components/agents/base.py", line 3')
        assert derive_candidate_path(payload) == "components/agents/base.py"

    def test_dotted_module_fallback(self):
        payload = _payload(
            "cannot import name 'refresh_recommendable_items' from components.knowledge.application.embedding_service"
        )
        assert derive_candidate_path(payload) == "components/knowledge/application/embedding_service.py"

    def test_longest_dotted_module_wins(self):
        payload = _payload("module workflow.tasks failed importing components.workflow.infrastructure.tasks.runner")
        assert derive_candidate_path(payload) == "components/workflow/infrastructure/tasks/runner.py"

    def test_hostnames_are_not_modules(self):
        payload = _payload("connection to sqs.us-east-1.amazonaws.com timed out")
        assert derive_candidate_path(payload) is None

    def test_no_file_evidence_returns_none(self):
        payload = _payload("something went wrong")
        assert derive_candidate_path(payload) is None


_OLD_CONTENT = "def run_due_schedules():\n    return schedule()\n\n\ndef other():\n    return 1\n"


def _llm_json(updated: str, path: str = "components/workflow/tasks.py", summary: str = "fix") -> str:
    return json.dumps({"path": path, "updated_content": updated, "change_summary": summary})


@pytest.mark.unit
class TestPatchGroundedness:
    def _propose(self, llm_content: str, payload: dict | None = None, old: str = _OLD_CONTENT):
        advisor = LogPatchAdvisor(llm_port=_FakeLlm(llm_content))
        payload = payload or _payload(
            "NameError: name 'schedule' is not defined in run_due_schedules",
            suggested_fix="Import schedule in the module.",
        )
        return advisor.propose(payload=payload, path="components/workflow/tasks.py", current_content=old)

    def test_grounded_patch_touching_salient_token_line_is_accepted(self):
        # Missing-export fix: the ADDED lines carry the finding's salient
        # token (run_due_schedules_hourly) — grounded.
        payload = _payload(
            "ImportError: cannot import name 'run_due_schedules_hourly' from workflow tasks",
            suggested_fix="Add run_due_schedules_hourly to the module.",
        )
        updated = _OLD_CONTENT + "\n\ndef run_due_schedules_hourly():\n    return run_due_schedules()\n"
        proposal = self._propose(_llm_json(updated), payload=payload)
        assert proposal is not None
        assert proposal.path == "components/workflow/tasks.py"
        assert "def run_due_schedules_hourly" in proposal.updated_content

    def test_patch_touching_only_unrelated_lines_is_rejected(self):
        updated = _OLD_CONTENT.replace("def other():\n    return 1", "def other():\n    return 2")
        assert self._propose(_llm_json(updated)) is None

    def test_identical_content_is_rejected(self):
        assert self._propose(_llm_json(_OLD_CONTENT)) is None

    def test_unparseable_output_is_rejected(self):
        assert self._propose("I think you should probably fix the import.") is None

    def test_empty_updated_content_is_rejected(self):
        assert self._propose(_llm_json("")) is None

    def test_evidence_with_no_salient_tokens_is_rejected(self):
        payload = {
            "service": "web",
            "level": "ERROR",
            "message": "it broke",
            "signal": "",
            "evidence": [],
            "suggested_fix": "",
        }
        updated = _OLD_CONTENT + "# fixed\n"
        assert self._propose(_llm_json(updated), payload=payload) is None

    def test_oversized_file_degrades_to_none(self):
        advisor = LogPatchAdvisor(llm_port=_FakeLlm(_llm_json(_OLD_CONTENT + "# x\n")))
        payload = _payload("NameError: run_due_schedules")
        big = "x = 1\n" * 30_000
        assert advisor.propose(payload=payload, path="a.py", current_content=big) is None

    def test_code_fenced_json_is_salvaged(self):
        payload = _payload(
            "ImportError: cannot import name 'run_due_schedules_hourly'",
            suggested_fix="Add run_due_schedules_hourly.",
        )
        updated = _OLD_CONTENT + "\n\ndef run_due_schedules_hourly():\n    return None\n"
        fenced = f"```json\n{_llm_json(updated)}\n```"
        assert self._propose(fenced, payload=payload) is not None

    def test_llm_failure_degrades_to_none(self):
        class _Boom:
            def chat(self, messages):
                raise RuntimeError("llm down")

        advisor = LogPatchAdvisor(llm_port=_Boom())
        payload = _payload("NameError: run_due_schedules")
        assert advisor.propose(payload=payload, path="a.py", current_content=_OLD_CONTENT) is None
