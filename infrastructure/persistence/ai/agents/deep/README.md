# Deep Agent Pattern (LangGraph/LangChain/MCP/Context7)

Guidance for building deep plans that delegate to domain agents.

## Goals
- Keep orchestration in the orchestrator/planner; domain agents remain focused executors.
- Model plans as explicit graphs (LangGraph) with checkpoints for resumability.
- Use MCP providers for external tools (APIs, FS, doc search) and Context7 for docs retrieval instead of ad-hoc scraping.

## Minimal LangGraph Shape
1) **plan**: LLM produces structured task list (include seed_id, task type, owner hints).
2) **route**: map each task to a domain agent (`task_agent`, `project_agent`, etc.).
3) **execute**: call the domain agent via the orchestrator’s `create_agent_tool` invokers; persist results.
4) **checkpoint**: store graph state in DB (see `apps/ai/agents/deep/checkpoints` patterns).
5) **review**: optional summariser node; log AI actions for approvals.

Pseudo-skeleton:
```python
from langgraph.graph import StateGraph, END
from apps.ai.agents.tools.agent_bridge import create_agent_tool

def build_graph(orchestrator):
    g = StateGraph(dict)

    def plan_node(state):
        # produce state["tasks"] = [...]
        ...
    g.add_node("plan", plan_node)

    def route_node(state):
        # attach agent_type per task
        ...
    g.add_node("route", route_node)

    task_tool, invoke_task = create_agent_tool(orchestrator, "task_agent", "delegate tasks")

    def execute_node(state):
        for task in state["tasks"]:
            if task["agent_type"] == "task_agent":
                result = invoke_task(task["prompt"], {"seed_id": orchestrator.seed_id})
                task["result"] = result
        return state
    g.add_node("execute", execute_node)

    g.set_entry_point("plan")
    g.add_edge("plan", "route")
    g.add_edge("route", "execute")
    g.add_edge("execute", END)
    return g.compile()
```

## MCP / Context7
- Register MCP providers at the orchestrator/deep layer so downstream calls stay auditable.
- For docs, use Context7 query APIs instead of arbitrary HTTP; cache references in state for reproducibility.

## Storage / Checkpointing
- Use the DB-backed saver in `apps/ai/agents/deep/checkpoints` to persist graph state and resume runs.
- Store agent invocation outputs (tool responses) alongside plan state to support replay/approval.

## What to Avoid
- Domain agents should not route to other agents.
- Avoid scattering LangGraph construction inside views; place reusable builders under `apps/ai/agents/deep/`.
- Do not scrape docs directly; go through MCP/Context7.

## Next Steps
- If adding a new deep flow, follow this template and register the entrypoint under `apps/ai/agents/deep/` with tests for plan/execute nodes.

## Example: Deep Project Agent (scaffold)
- Location: `apps/ai/agents/deep/project.py`
- Default behavior: deterministic planner that emits a small task list; stub worker that marks tasks completed (no side effects) for dev/test.
- Extend by:
  - Swapping the planner to an LLM + org context (team, budgets, constraints).
  - Replacing the worker with orchestrator invokers that call TaskAgent/ProjectAgent/BudgetAgent to create the real project, tasks, and budget.
  - Persisting artifacts via `store_artifact` and checkpointing via `default_checkpointer`.
