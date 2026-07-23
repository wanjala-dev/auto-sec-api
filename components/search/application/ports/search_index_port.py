"""Driven port for workspace suggest lookups.

The application service orchestrates per-section suggest queries through
this port; the Postgres adapter in
``components/search/infrastructure/repositories/postgres_suggest_repository.py``
implements it with ``icontains`` ORM queries.

Every suggest method returns a list of plain item dicts with the uniform
contract the HUD search renders:

    {"id": str, "title": str, "subtitle": str, "url": str}

Finding items additionally carry ``severity`` (band: critical/high/medium/low,
or "") and ``score`` (indicative CVSS float, or None) so the omnibox can render
a severity score badge.

``url`` is the FRONTEND route the client navigates to on click (the
auto-sec frontend is a single-screen HUD, so routes are ``/`` plus
``?panel=…`` deep-links).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class SearchIndexPort(ABC):
    """Port over the searchable workspace surface (findings, tasks, agents,
    conversations, members, log services)."""

    @abstractmethod
    def active_workspace_ids(self, *, user_id) -> list[str]:
        """Workspace ids where the user holds an ACTIVE membership."""

    @abstractmethod
    def suggest_findings(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        """AI-filed finding tasks (``source_type`` startswith ``ai.``)."""

    @abstractmethod
    def suggest_tasks(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        """Human/board tasks (everything that is not an AI finding)."""

    @abstractmethod
    def suggest_agents(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        """Agent profiles in the workspace + the active agent-type catalog."""

    @abstractmethod
    def suggest_conversations(self, *, user_id, q: str, limit: int) -> list[dict]:
        """The requesting user's own AI conversations (never other users')."""

    @abstractmethod
    def suggest_members(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        """Active members of the scoped workspaces only — never leaks users
        outside the requester's workspaces."""

    @abstractmethod
    def suggest_log_services(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        """Distinct ``LogPatternRollup.service`` values matching the query."""
