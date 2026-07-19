"""Step isolation for deep-run execution.

Each deep-run step gets its own scoped context: filtered tools,
isolated memory window, and budget limits.  This prevents one step's
failures from polluting another and enables parallel step execution.

Pure domain service — no ORM, no LangChain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StepContext:
    """Isolated execution context for a single deep-run step."""

    step_id: str
    task_title: str
    run_id: str
    workspace_id: str
    user_id: str
    agent_type: str

    # Tool policy — restrict which tools this step can use
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    blocked_tools: frozenset[str] = field(default_factory=frozenset)

    # Memory isolation — each step gets its own conversation thread
    conversation_id: str = ""

    # Memory limits for this step
    max_messages: int = 20
    max_message_chars: int = 1500
    max_total_chars: int = 8000

    # Budget limits for this step
    max_iterations: int = 10
    max_execution_time_seconds: int = 30

    # Extra context injected into the step's system prompt
    step_instructions: str = ""
    prior_step_summaries: list[str] = field(default_factory=list)

    def as_run_context(self) -> dict[str, Any]:
        """Convert to the run_context dict expected by BaseAgent._apply_run_context."""
        ctx: dict[str, Any] = {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "memory_limits": {
                "max_messages": self.max_messages,
                "max_message_chars": self.max_message_chars,
                "max_total_chars": self.max_total_chars,
            },
        }
        if self.allowed_tools:
            ctx["allowed_tools"] = list(self.allowed_tools)
        if self.blocked_tools:
            ctx["blocked_tools"] = list(self.blocked_tools)
        return ctx

    def build_step_prompt_prefix(self) -> str:
        """Build context that gets prepended to the step's prompt."""
        parts: list[str] = []

        if self.step_instructions:
            parts.append(f"## Step Instructions\n{self.step_instructions}")

        if self.prior_step_summaries:
            summaries = "\n".join(
                f"- Step {i + 1}: {s}"
                for i, s in enumerate(self.prior_step_summaries)
            )
            parts.append(f"## Context from prior steps\n{summaries}")

        return "\n\n".join(parts)


def build_step_contexts(
    *,
    run_id: str,
    workspace_id: str,
    user_id: str,
    agent_type: str,
    tasks: list[dict[str, Any]],
    global_allowed_tools: frozenset[str] | None = None,
    global_blocked_tools: frozenset[str] | None = None,
) -> list[StepContext]:
    """Build isolated contexts for each task in a deep-run plan.

    Each step gets:
    - Its own conversation_id (derived from run_id + step index)
    - Tool restrictions from the task spec + global policy
    - Memory limits scaled to the step's expected complexity
    """
    import uuid

    contexts: list[StepContext] = []
    prior_summaries: list[str] = []

    for idx, task in enumerate(tasks):
        step_id = task.get("id") or f"step-{idx}"
        title = task.get("title", f"Step {idx + 1}")

        # Per-step tool restrictions
        step_tools = frozenset(task.get("allowed_tools", []))
        if global_allowed_tools and step_tools:
            allowed = step_tools & global_allowed_tools
        elif global_allowed_tools:
            allowed = global_allowed_tools
        else:
            allowed = step_tools

        blocked = frozenset(task.get("blocked_tools", []))
        if global_blocked_tools:
            blocked = blocked | global_blocked_tools

        ctx = StepContext(
            step_id=step_id,
            task_title=title,
            run_id=run_id,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_type=agent_type,
            allowed_tools=allowed,
            blocked_tools=blocked,
            conversation_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{run_id}:{step_id}")),
            step_instructions=task.get("description", ""),
            prior_step_summaries=list(prior_summaries),
        )
        contexts.append(ctx)
        prior_summaries.append(title)

    return contexts
