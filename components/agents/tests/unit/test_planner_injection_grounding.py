"""SEE-200 — the active planner prompt carries the injection-defence grounding.

A contract test: the deep planner treats retrieved chunk content as untrusted
data, never as instructions. Locking it here means a later `active` version
flip (or a grounding rewrite) that drops the defence fails loudly instead of
silently reopening the indirect-prompt-injection vector.
"""

from __future__ import annotations

from components.agents.infrastructure.prompts.registry import PromptRegistry


class TestPlannerInjectionGrounding:
    def test_active_planner_prompt_frames_retrieved_content_as_untrusted(self):
        prompt = PromptRegistry.get("planner.system")

        assert "untrusted content" in prompt
        # It must say instructions embedded in chunks are not commands to obey.
        assert "rather than that embedded text" in prompt
        # The defence carries a because-clause naming indirect prompt injection.
        assert "indirect prompt injection" in prompt

    def test_active_planner_prompt_references_the_untrusted_flag(self):
        prompt = PromptRegistry.get("planner.system")

        assert "untrusted: true" in prompt
