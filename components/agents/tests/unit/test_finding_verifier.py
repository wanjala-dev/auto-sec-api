"""Unit tests for the grounded finding verifier — deterministic, no LLM.

Asserts the verifier PASSES a suggestion grounded in the finding's evidence,
FAILS a generic/boilerplate one, and is CONSERVATIVE (passes when the evidence
offers no checkable specifics — never over-blocks a real fix).
"""

from __future__ import annotations

from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion


class TestTriageGroundedness:
    def _payload(self):
        return {
            "service": "celery_worker",
            "level": "ERROR",
            "message": "cannot import name 'AiEmbeddingsProvider' from 'components.knowledge.providers'",
            "evidence": [{"type": "log_line", "detail": "ImportError: cannot import name 'AiEmbeddingsProvider'"}],
        }

    def test_grounded_fix_referencing_symbol_passes(self):
        vr = verify_suggestion(
            source_type="ai.log_watch",
            payload=self._payload(),
            suggestion_text="Ensure AiEmbeddingsProvider is exported from components.knowledge.providers.",
        )
        assert vr.grounded is True

    def test_grounded_fix_referencing_service_passes(self):
        vr = verify_suggestion(
            source_type="ai.log_watch",
            payload=self._payload(),
            suggestion_text="Restart the celery_worker after fixing the import.",
        )
        assert vr.grounded is True

    def test_generic_boilerplate_fails(self):
        vr = verify_suggestion(
            source_type="ai.log_watch",
            payload=self._payload(),
            suggestion_text="Investigate further by checking additional logs and monitoring the system.",
        )
        assert vr.grounded is False
        assert "generic" in vr.reason.lower()

    def test_no_checkable_specifics_passes_conservatively(self):
        # Evidence with no code-like tokens and no service → can't disprove.
        vr = verify_suggestion(
            source_type="ai.log_watch",
            payload={"service": "", "message": "boom", "evidence": []},
            suggestion_text="Look into it.",
        )
        assert vr.grounded is True

    def test_empty_suggestion_fails(self):
        vr = verify_suggestion(source_type="ai.log_watch", payload=self._payload(), suggestion_text="")
        assert vr.grounded is False


class TestOptimizationGroundedness:
    def _payload(self):
        return {
            "kind": "periodic_task",
            "service": "celery_beat",
            "subject": "workflow.run_due_schedules",
            "frequency": {"last_window": 41},
        }

    def test_concrete_change_passes(self):
        vr = verify_suggestion(
            source_type="ai.log_optimization",
            payload=self._payload(),
            suggestion_text="Raise the beat interval from */5 to */15 to cut scheduler wakeups.",
        )
        assert vr.grounded is True

    def test_concrete_without_echoing_task_name_passes(self):
        # Names no task path, but proposes a concrete sampling change → grounded.
        vr = verify_suggestion(
            source_type="ai.log_optimization",
            payload=self._payload(),
            suggestion_text="Sample these health-check logs at 10% instead of logging every one.",
        )
        assert vr.grounded is True

    def test_vague_reduction_advice_fails(self):
        vr = verify_suggestion(
            source_type="ai.log_optimization",
            payload=self._payload(),
            suggestion_text="Monitor the system and investigate the noisy component.",
        )
        assert vr.grounded is False
        assert "concrete" in vr.reason.lower()
