"""Postgres suggest adapter — implements :class:`SearchIndexPort`.

Plain ``icontains`` ORM lookups, workspace-scoped wherever the model has a
workspace FK, ``.values()``-projected and sliced to the caller's limit so
no full model instances are materialised. ORM imports stay inside method
bodies (lazy) so importing this module never drags Django app loading
forward.

Item ``url`` values are FRONTEND routes. The auto-sec frontend is a
single-screen HUD (see the frontend's ``single-screen-hud`` rule): every
surface is a panel over ``/``, deep-linked via ``?panel=<id>`` (and
``&section=<id>`` for settings). The routes used here:

* findings / tasks → ``/?panel=kanban``            (SOC triage board)
* agents           → ``/``                          (agent hexes on the HUD)
* conversations    → ``/``                          (chat opens by thread)
* members          → ``/?panel=settings&section=members``
* log_services     → ``/?panel=documents``          (LOGS panel)
"""

from __future__ import annotations

from collections.abc import Sequence

from components.search.application.ports.search_index_port import SearchIndexPort

_FINDINGS_URL = "/?panel=kanban"
_TASKS_URL = "/?panel=kanban"
_AGENTS_URL = "/"
_CONVERSATIONS_URL = "/"
_MEMBERS_URL = "/?panel=settings&section=members"
_LOG_SERVICES_URL = "/?panel=documents"

_AI_SOURCE_PREFIX = "ai."

# Indicative CVSS 3.1 base score per severity band — the midpoint of each band's
# CVSS range (Critical 9.0-10 → 9.5, High 7-8.9 → 8.0, Medium 4-6.9 → 5.5, Low
# 0.1-3.9 → 2.5). Same mapping the report deliverable uses: we run no scanner
# that emits a vector, so this is an INDICATIVE band score, not vector-derived.
# Surfaced on finding suggest items so the omnibox can render a score badge.
_INDICATIVE_CVSS = {"critical": 9.5, "high": 8.0, "medium": 5.5, "low": 2.5}


class PostgresSuggestRepository(SearchIndexPort):
    """Suggest lookups over the shared persistence layer."""

    def active_workspace_ids(self, *, user_id) -> list[str]:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        return [
            str(workspace_id)
            for workspace_id in WorkspaceMembership.objects.filter(
                user_id=user_id,
                status=WorkspaceMembership.Status.ACTIVE,
            ).values_list("workspace_id", flat=True)
        ]

    def suggest_findings(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        from django.db.models import Q

        from infrastructure.persistence.project.models import Task

        rows = (
            Task.objects.filter(
                workspace_id__in=workspace_ids,
                source_type__startswith=_AI_SOURCE_PREFIX,
            )
            .filter(Q(title__icontains=q) | Q(description__icontains=q))
            .order_by("-created_at")
            .values("id", "title", "source_type", "metadata")[:limit]
        )
        items = []
        for row in rows:
            band = self._finding_severity_band(row)
            items.append(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "subtitle": self._finding_subtitle(row),
                    "url": _FINDINGS_URL,
                    # Severity band + indicative score so the omnibox renders a
                    # coloured score badge (empty band / null score when unknown).
                    "severity": band,
                    "score": _INDICATIVE_CVSS.get(band),
                }
            )
        return items

    def suggest_tasks(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        from infrastructure.persistence.project.models import Task

        rows = (
            Task.objects.filter(
                workspace_id__in=workspace_ids,
                title__icontains=q,
            )
            .exclude(source_type__startswith=_AI_SOURCE_PREFIX)
            .order_by("-created_at")
            .values("id", "title", "column__title")[:limit]
        )
        return [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "subtitle": row["column__title"] or "",
                "url": _TASKS_URL,
            }
            for row in rows
        ]

    def suggest_agents(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        from django.db.models import Q

        from infrastructure.persistence.ai.agents.models import AgentProfile, AgentType

        items: list[dict] = []
        profile_rows = (
            AgentProfile.objects.filter(
                agent__workspace_id__in=workspace_ids,
                is_disabled=False,
            )
            .filter(Q(display_name__icontains=q) | Q(summary__icontains=q))
            .order_by("-updated_at")
            .values("agent_id", "display_name", "agent__agent_type")[:limit]
        )
        for row in profile_rows:
            items.append(
                {
                    "id": str(row["agent_id"]),
                    "title": row["display_name"] or row["agent__agent_type"],
                    "subtitle": row["agent__agent_type"],
                    "url": _AGENTS_URL,
                }
            )

        remaining = limit - len(items)
        if remaining > 0:
            type_rows = (
                AgentType.objects.filter(is_active=True)
                .filter(Q(name__icontains=q) | Q(description__icontains=q))
                .order_by("name")
                .values("id", "name", "slug")[:remaining]
            )
            items.extend(
                {
                    "id": str(row["id"]),
                    "title": row["name"],
                    "subtitle": row["slug"],
                    "url": _AGENTS_URL,
                }
                for row in type_rows
            )
        return items

    def suggest_conversations(self, *, user_id, q: str, limit: int) -> list[dict]:
        from infrastructure.persistence.ai.conversations.models import Conversation

        rows = (
            Conversation.objects.filter(
                user_id=user_id,
                is_active=True,
                title__icontains=q,
            )
            .order_by("-updated_at")
            .values("id", "title", "updated_at")[:limit]
        )
        return [
            {
                "id": str(row["id"]),
                "title": row["title"] or "Untitled conversation",
                "subtitle": row["updated_at"].date().isoformat() if row["updated_at"] else "",
                "url": _CONVERSATIONS_URL,
            }
            for row in rows
        ]

    def suggest_members(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        from django.db.models import Q

        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        rows = (
            WorkspaceMembership.objects.filter(
                workspace_id__in=workspace_ids,
                status=WorkspaceMembership.Status.ACTIVE,
                user__is_active=True,
            )
            .filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__email__icontains=q)
            )
            .order_by("user_id")
            .values(
                "user_id",
                "role",
                "user__first_name",
                "user__last_name",
                "user__username",
                "user__email",
            )[: limit * 3]
        )
        items: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            user_id = str(row["user_id"])
            if user_id in seen:
                continue  # same user in several scoped workspaces
            seen.add(user_id)
            full_name = " ".join(part for part in (row["user__first_name"], row["user__last_name"]) if part)
            items.append(
                {
                    "id": user_id,
                    "title": full_name or row["user__username"] or row["user__email"],
                    "subtitle": row["role"],
                    "url": _MEMBERS_URL,
                }
            )
            if len(items) >= limit:
                break
        return items

    def suggest_log_services(self, *, workspace_ids: Sequence[str], q: str, limit: int) -> list[dict]:
        from infrastructure.persistence.integrations.models import LogPatternRollup

        services = (
            LogPatternRollup.objects.filter(
                workspace_id__in=workspace_ids,
                service__icontains=q,
            )
            .exclude(service="")
            .order_by("service")
            .values_list("service", flat=True)
            .distinct()[:limit]
        )
        return [
            {
                "id": service,
                "title": service,
                "subtitle": "log service",
                "url": _LOG_SERVICES_URL,
            }
            for service in services
        ]

    @staticmethod
    def _finding_severity_band(row: dict) -> str:
        """Normalised severity band (critical/high/medium/low) or "" if unknown."""
        metadata = row.get("metadata") or {}
        payload = metadata.get("payload") or {}
        band = str(metadata.get("severity") or payload.get("severity") or "").strip().lower()
        return band if band in _INDICATIVE_CVSS else ""

    @staticmethod
    def _finding_subtitle(row: dict) -> str:
        metadata = row.get("metadata") or {}
        payload = metadata.get("payload") or {}
        severity = metadata.get("severity") or payload.get("severity") or ""
        kind = payload.get("kind") or ""
        if severity and kind:
            return f"{severity} · {kind}"
        if severity or kind:
            return severity or kind
        # Fall back to the detector key carried on source_type (``ai.<key>``).
        source_type = row.get("source_type") or ""
        return source_type.removeprefix(_AI_SOURCE_PREFIX)
