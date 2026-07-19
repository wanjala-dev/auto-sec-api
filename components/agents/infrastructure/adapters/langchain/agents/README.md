# Agents (auto-discovered)

Drop a new agent module in this directory. `discover_agents()` walks the package at Django startup and runs your `@register_agent` decorator. **No edits to `base.py` or any other file are required.**

See [ADR 0003 — Agent Decorator Framework](../../../../../../docs/adr/0003-agent-decorator-framework.md) for the full rationale.

## Quick start: add a new agent in one file

Copy this template into a new file in this directory (e.g. `marketplace_agent.py`). The filename doesn't matter — auto-discovery picks up every public module.

```python
"""Marketplace Management Agent."""

from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    requires_role,
    tool,
)
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.marketplace.application import marketplace_service  # your domain service


@register_agent("marketplace_agent", aliases=("marketplace", "shop", "listings"))
class MarketplaceAgent(WorkspaceContextMixin, BaseAgent):
    """Manages marketplace listings, orders, and revenue analytics."""

    profile = {
        "name": "Marketplace Agent",
        "summary": (
            "Creates and manages marketplace listings, processes orders, "
            "and surfaces revenue analytics for the workspace."
        ),
        "capabilities": [
            "Create, edit, and publish listings",
            "Track inventory and update prices",
            "Process orders and update fulfillment",
            "Surface bestsellers and low-stock alerts",
            "Generate revenue reports",
        ],
        "sample_prompts": [
            "What are my top-selling items this month?",
            "Mark order #1234 as shipped",
            "List all out-of-stock listings",
        ],
    }

    @tool(
        name="list_listings",
        description=(
            "List marketplace listings in this workspace. Input: optional "
            "filter (e.g. 'active', 'out-of-stock', 'category:books'). "
            "Output: a formatted list of listings with title, price, "
            "and inventory."
        ),
    )
    def list_listings(self, input_str: str = "") -> str:
        """Default behavior: return all active listings, sorted by recency."""
        return marketplace_service.list_listings(
            workspace_id=self.workspace_id,
            actor_id=self.user_id,
            filter_expr=input_str,
        )

    @tool(
        name="create_listing",
        description=(
            "Create a new marketplace listing. Input: JSON-ish string with "
            "title, price, category, and inventory. Output: listing details "
            "or an error message."
        ),
    )
    @requires_role("owner", "admin", "member")
    def create_listing(self, input_str: str) -> str:
        return marketplace_service.create_listing(
            workspace_id=self.workspace_id,
            actor_id=self.user_id,
            payload=input_str,
        )

    @tool(
        name="delete_listing",
        description="Permanently delete a listing. Input: listing_id.",
    )
    @requires_role("owner", "admin")
    def delete_listing(self, listing_id: str) -> str:
        return marketplace_service.delete_listing(
            workspace_id=self.workspace_id,
            actor_id=self.user_id,
            listing_id=listing_id,
        )
```

That's the entire file. Restart the dev server (or in a Django shell call `discover_agents()` directly) and the agent appears in `AgentRegistry.list_agents()` under all four names.

## What you get for free

By inheriting from `BaseAgent` (and optionally a mixin), every agent automatically gets:

- The full ReAct loop, telemetry, tracing, retry logic, memory service, and prompt customization (persona, tone, output format) — all of which `BaseAgent.__init__` wires up.
- The `whoami` and `get_workspace_info` tools if you mix in `WorkspaceContextMixin`.
- The meta-query handler — when a user asks *"what can you do?"* the agent answers from your `profile` class attribute.
- Permission gating via `@requires_role(...)` reading the RBAC role from `WorkspaceMembership` (see [ADR 0002](../../../../../../docs/adr/0002-personas-and-rbac.md)).

## Tool authoring rules

1. **Tool names must be stable.** They're stored in DB `Agent.config["custom_profile"]["tool_whitelist"]` configs. If you rename a tool, you have to migrate the DB.
2. **Descriptions matter.** They're the LLM's only guide for which tool to call. Be specific about input format and output shape. Bad descriptions → wrong tool calls.
3. **Always call into your existing application services**, never the ORM directly. The service layer is where validation, permissions, and audit live. Bypassing it creates security holes.
4. **Don't `raise`.** Tools return strings (or `ToolResult` instances). Raising propagates an exception up through the executor and surfaces to the user as a generic error. Catch your own exceptions and return a friendly string.
5. **Pure functions where possible.** Tools should be repeatable — same input → same output. Side-effecting tools (create, update, delete) need permission gates.

## Testing your agent

```python
from components.agents.infrastructure.adapters.langchain.agents.marketplace_agent import (
    MarketplaceAgent,
)
from components.agents.tests.agent_test_case import AgentTestCase


class MarketplaceAgentTests(AgentTestCase):
    def test_count_listings(self):
        self.mock_tool_returns("list_listings", "5 active listings")
        self.mock_llm_chooses("list_listings", "active")
        agent = self.make_agent(MarketplaceAgent)

        result = agent.agent_executor.invoke({"input": "how many listings"})

        self.assert_tool_called("list_listings")
        self.assertIn("5 active", result["output"])
```

The harness fakes the LLM, the executor, and the memory service. No real OpenAI calls. Tests run in milliseconds.

## When to add a mixin instead of an agent

If a set of tools is useful across multiple agents (e.g. *"list workspace members"*, *"get workspace metadata"*, *"check current user's permissions"*), put them in a new `_*.py` file in this directory and have agents inherit from it. The leading underscore tells `discover_agents()` to skip the file (mixins aren't agents).

```python
# _analytics_mixin.py
from components.agents.infrastructure.adapters.langchain.base import tool


class AnalyticsMixin:
    @tool(name="get_workspace_kpis", description="...")
    def get_workspace_kpis(self) -> str:
        ...

# marketplace_agent.py
from ._analytics_mixin import AnalyticsMixin

@register_agent("marketplace")
class MarketplaceAgent(AnalyticsMixin, WorkspaceContextMixin, BaseAgent):
    ...
```

The MRO de-duplicates tool names, so two mixins defining the same tool is safe — leftmost wins.

## File layout

```
agents/
├── __init__.py            # discover_agents()
├── _mixins.py             # WorkspaceContextMixin (and future mixins)
├── README.md              # this file
└── blog_agent.py          # worked example
└── marketplace_agent.py   # add yours here
```

## Migration of legacy agents

The 10 agents still under `components/agents/infrastructure/adapters/langchain/{name}_agent.py` (ProjectAgent, TaskAgent, BudgetAgent, etc.) use the legacy `_setup_tools` override pattern. They work fine — there's no deadline to migrate them. When you next touch one of them, consider migrating it as a side effect:

1. Move the file to `agents/{name}_agent.py`.
2. Add `@register_agent("name", aliases=(...))` on the class.
3. Convert each `Tool(...)` entry from `_setup_tools` into a `@tool` method that calls the same underlying function.
4. Add a `profile = {...}` class attribute.
5. Delete the `_setup_tools` override.
6. Remove the manual import + register lines from `base.py` (lines ~1230-1290).
7. Restart the server. Verify `AgentRegistry.list_agents()` is unchanged.

The migration guide for `BlogAgent` is the worked example you can copy from. See `agents/blog_agent.py`.
