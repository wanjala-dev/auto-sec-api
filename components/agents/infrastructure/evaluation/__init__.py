"""Prompt evaluation infrastructure.

Implements the 5-step evaluation workflow from Anthropic's prompt-eval
curriculum (Logseq notes, 2026-04-24 / 2026-05-05):

    1. Draft a prompt
    2. Create an eval dataset
    3. Feed each through the model
    4. Feed responses through a grader (1-10 with reasoning)
    5. Change the prompt, repeat

The :class:`PromptEvaluator` orchestrates steps 3 and 4 against any
``run_prompt_function`` (so the planner, project planner, task
planner, and estimator can all share one harness). Graders live in
:mod:`code_graders` (deterministic) and :mod:`model_graders`
(LLM-as-judge).

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 2.
"""
