"""Application service for the search bounded context.

Framework-free orchestration: caps the limit, enforces the minimum query
length, resolves the workspace scope from the requester's memberships
(raising :class:`WorkspaceAccessDenied` when an explicit ``workspace_id``
is outside them), fans out to the per-section suggest queries via the
:class:`SearchIndexPort`, and returns only the non-empty sections.
"""

from __future__ import annotations

from components.search.application.ports.search_index_port import SearchIndexPort
from components.search.domain.errors import WorkspaceAccessDenied


class SearchSuggestService:
    """Single front door for suggest queries."""

    MIN_QUERY_LENGTH = 2
    DEFAULT_LIMIT = 6
    MAX_LIMIT = 10

    # Render order the frontend mirrors (SECTION_DISPLAY_ORDER).
    SECTION_ORDER = (
        "findings",
        "tasks",
        "agents",
        "conversations",
        "members",
        "log_services",
    )

    def __init__(self, index: SearchIndexPort):
        self._index = index

    def suggest(self, *, user_id, q: str, limit: int | None = None, workspace_id: str | None = None) -> dict:
        """Return ``{section: [items…]}`` for non-empty sections only.

        ``workspace_id`` narrows the scope to one workspace the requester
        must be an active member of; absent, all their active memberships
        are searched. Conversations are always scoped to the requesting
        user, independent of workspace.
        """
        query = (q or "").strip()
        capped_limit = self._cap_limit(limit)
        if len(query) < self.MIN_QUERY_LENGTH:
            return {}

        member_workspace_ids = [str(w) for w in self._index.active_workspace_ids(user_id=user_id)]
        if workspace_id:
            if str(workspace_id) not in member_workspace_ids:
                raise WorkspaceAccessDenied(str(workspace_id))
            scope = [str(workspace_id)]
        else:
            scope = member_workspace_ids

        sections: dict[str, list[dict]] = {}
        if scope:
            sections["findings"] = self._index.suggest_findings(workspace_ids=scope, q=query, limit=capped_limit)
            sections["tasks"] = self._index.suggest_tasks(workspace_ids=scope, q=query, limit=capped_limit)
            sections["agents"] = self._index.suggest_agents(workspace_ids=scope, q=query, limit=capped_limit)
            sections["members"] = self._index.suggest_members(workspace_ids=scope, q=query, limit=capped_limit)
            sections["log_services"] = self._index.suggest_log_services(
                workspace_ids=scope, q=query, limit=capped_limit
            )
        sections["conversations"] = self._index.suggest_conversations(user_id=user_id, q=query, limit=capped_limit)

        return {key: sections[key] for key in self.SECTION_ORDER if sections.get(key)}

    def _cap_limit(self, limit: int | None) -> int:
        if not isinstance(limit, int) or limit <= 0:
            return self.DEFAULT_LIMIT
        return min(limit, self.MAX_LIMIT)
