"""Unit tests — grounding reaches the advisor prompt, and STILL runs the guardrail (ADR 0012 D2).

Two claims, both load-bearing for the security spine:

1. When a workspace is supplied, the team's vetted prior fixes are folded into the
   advisor's prompt BEFORE it proposes (grounded, not hallucinated). When no
   workspace is supplied, retrieval is skipped entirely — the ungrounded path is
   byte-for-byte unchanged.
2. **D2 — retrieval grounds, it NEVER authorizes.** A grounded candidate is STILL
   run through the guardrail: ``validate_patch`` for the patch flow, ``verify_suggestion``
   for the comment flow. A destructive/ungrounded output does not reach a PR just
   because a prior was retrieved.

No DB, no real LLM, no real retrieval — a scripted fake LLM captures the prompt and
a fake ``RemediationRetrievalPort`` returns canned priors.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import (
    verify_suggestion,
)
from components.integrations.application.log_fix_advisor_service import LogFixAdvisor
from components.integrations.application.log_patch_advisor_service import (
    LogPatchAdvisor,
    PatchValidationError,
    validate_patch,
)
from components.remediation.application.ports.remediation_retrieval_port import (
    RemediationGroundingDTO,
)


class _CapturingLlm:
    def __init__(self, content: str):
        self._content = content
        self.last_user_prompt = ""

    def chat(self, messages):
        self.last_user_prompt = messages[-1]["content"]
        return SimpleNamespace(content=self._content)


class _FakeRetrieval:
    def __init__(self, dtos):
        self._dtos = dtos
        self.calls = 0
        self.last_kwargs: dict = {}

    def retrieve_grounding(self, *, workspace_id, finding_kind, query_text, top_k=3):
        self.calls += 1
        self.last_kwargs = {"workspace_id": workspace_id, "finding_kind": finding_kind, "query_text": query_text}
        return list(self._dtos)


_PRIOR = RemediationGroundingDTO(
    finding_kind="log_watch",
    language="python",
    title="Prior casing fix",
    summary="added an alias instead of deleting the module",
    code="AiEmbeddingsProvider = AIEmbeddingsProvider",
    tags=("import",),
)


def _log_payload(message: str) -> dict:
    return {
        "service": "worker",
        "level": "ERROR",
        "message": message,
        "signal": message,
        "evidence": [{"type": "log_line", "detail": message}],
        "suggested_fix": "",
    }


@pytest.mark.unit
class TestPatchAdvisorGrounding:
    def test_grounding_reaches_the_prompt(self):
        llm = _CapturingLlm('{"path": "m.py", "updated_content": "x = 1\\n", "change_summary": "s"}')
        retrieval = _FakeRetrieval([_PRIOR])
        advisor = LogPatchAdvisor(llm_port=llm, retrieval=retrieval)

        advisor.propose(
            payload=_log_payload("ImportError cannot import name 'run_due_schedules'"),
            path="m.py",
            current_content="def run_due_schedules():\n    return 1\n",
            workspace_id="ws-1",
            source_type="ai.log_watch",
        )

        assert retrieval.calls == 1
        assert retrieval.last_kwargs["workspace_id"] == "ws-1"
        assert retrieval.last_kwargs["finding_kind"] == "log_watch"  # ai. stripped
        assert "PRIOR VERIFIED FIXES" in llm.last_user_prompt
        assert "Prior casing fix" in llm.last_user_prompt
        assert "AiEmbeddingsProvider = AIEmbeddingsProvider" in llm.last_user_prompt

    def test_no_workspace_skips_retrieval_and_grounding(self):
        llm = _CapturingLlm('{"path": "m.py", "updated_content": "x = 1\\n", "change_summary": "s"}')
        retrieval = _FakeRetrieval([_PRIOR])
        advisor = LogPatchAdvisor(llm_port=llm, retrieval=retrieval)

        advisor.propose(
            payload=_log_payload("boom run_due_schedules"),
            path="m.py",
            current_content="def run_due_schedules():\n    return 1\n",
        )

        assert retrieval.calls == 0
        assert "PRIOR VERIFIED FIXES" not in llm.last_user_prompt

    def test_grounded_candidate_is_STILL_rejected_by_validate_patch(self):
        # D2: even with a prior retrieved and injected, a DESTRUCTIVE model output
        # (drops the very symbol the finding is about — the #828 shape) is produced
        # as a grounded candidate, and the guardrail STILL rejects it. Grounding
        # produced a candidate; validate_patch authorizes — the library did not.
        original = "def run_due_schedules():\n    return schedule()\n\n\ndef helper():\n    return 1\n"
        # A changed line carries the salient token (run_due_schedules), so the
        # advisor's groundedness gate passes and returns a candidate…
        gutted = "from x import run_due_schedules\n"
        llm = _CapturingLlm('{"path": "m.py", "updated_content": ' + _json_str(gutted) + ', "change_summary": "s"}')
        advisor = LogPatchAdvisor(llm_port=llm, retrieval=_FakeRetrieval([_PRIOR]))

        proposal = advisor.propose(
            payload=_log_payload("ImportError cannot import name 'run_due_schedules'"),
            path="m.py",
            current_content=original,
            workspace_id="ws-1",
            source_type="ai.log_watch",
        )
        assert proposal is not None  # a grounded candidate WAS produced

        # …and the guardrail still fires on it — grounding never bypasses D2.
        with pytest.raises(PatchValidationError) as exc:
            validate_patch(original_content=original, updated_content=proposal.updated_content, path="m.py")
        assert exc.value.reason == "patch_removes_definitions"


@pytest.mark.unit
class TestFixAdvisorGrounding:
    def test_grounding_reaches_the_prompt(self):
        llm = _CapturingLlm('{"likely_cause": "c", "suggested_fix": "add alias", "confidence": "high"}')
        retrieval = _FakeRetrieval([_PRIOR])
        advisor = LogFixAdvisor(llm_port=llm, retrieval=retrieval)

        advisor.suggest(
            service="worker",
            level="ERROR",
            message="ImportError cannot import name 'run_due_schedules'",
            workspace_id="ws-1",
            source_type="ai.log_watch",
        )

        assert retrieval.calls == 1
        assert retrieval.last_kwargs["finding_kind"] == "log_watch"
        assert "PRIOR VERIFIED FIXES" in llm.last_user_prompt
        assert "Prior casing fix" in llm.last_user_prompt

    def test_no_workspace_skips_retrieval(self):
        llm = _CapturingLlm('{"likely_cause": "c", "suggested_fix": "f", "confidence": "low"}')
        retrieval = _FakeRetrieval([_PRIOR])
        advisor = LogFixAdvisor(llm_port=llm, retrieval=retrieval)

        advisor.suggest(service="worker", level="ERROR", message="boom")

        assert retrieval.calls == 0
        assert "PRIOR VERIFIED FIXES" not in llm.last_user_prompt

    def test_grounded_suggestion_is_STILL_checked_by_verify_suggestion(self):
        # D2 (comment flow): a grounded prompt does not make an UNGROUNDED output
        # pass the evidence verifier. The advisor returns a suggestion unrelated to
        # the finding's salient tokens; verify_suggestion still rejects it.
        llm = _CapturingLlm(
            '{"likely_cause": "unknown", "suggested_fix": "restart the pod and clear the cache", "confidence": "high"}'
        )
        advisor = LogFixAdvisor(llm_port=llm, retrieval=_FakeRetrieval([_PRIOR]))

        message = "ImportError cannot import name 'run_due_schedules'"
        suggestion = advisor.suggest(
            service="worker", level="ERROR", message=message, workspace_id="ws-1", source_type="ai.log_watch"
        )
        assert suggestion is not None

        vr = verify_suggestion(
            source_type="ai.log_watch",
            payload=_log_payload(message),
            suggestion_text=f"{suggestion.likely_cause} {suggestion.suggested_fix}",
        )
        assert vr.grounded is False


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)
