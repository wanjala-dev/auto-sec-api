"""Agents surface — agent list reads.

Agent INVOCATION (chat, deep-run) is intentionally NOT in scope for load tests:
each invocation calls OpenAI under the hood and would burn budget under load.
Agent invocation belongs in dedicated cost-aware soak runs, not in the smoke set.
"""
from __future__ import annotations

from locust import task

from tests.load.base_users import AuthenticatedHttpUser


class AgentsLoadUser(AuthenticatedHttpUser):
    weight = 1

    @task(3)
    def list_agents(self) -> None:
        self.authed("get", "/ai/agents/", name="/ai/agents/")

    @task(1)
    def agent_health(self) -> None:
        self.authed("get", "/ai/health/", name="/ai/health/")
