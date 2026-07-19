"""Django/ORM adapter that loads workspace facts for the snapshot builder.

Lives in infrastructure — the only place the project allows ORM imports
for the Knowledge context.

Tier 2 #5/#6 extends the historical identity-only load with two
new dimensions: 30-day rollup counts and top-N entity lists.  Each
new block runs inside its own try/except so a future schema change
in one domain (e.g. Grant renaming a field) doesn't blank the entire
snapshot — at worst that one section drops and identity/mission still
embed.  See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #5/#6.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from components.knowledge.application.ports.workspace_snapshot_data_port import (
    WorkspaceSnapshotDataPort,
)
from components.knowledge.domain.value_objects.workspace_snapshot import (
    WorkspaceSnapshotInput,
)

logger = logging.getLogger(__name__)

# Tier 2 #5/#6 — windows and top-N caps.  30 days for "recent",
# 5 entries per top-N list.  Lifted to module level so tests can
# pin the values without touching the load() body.
RECENT_ACTIVITY_DAYS = 30
TOP_N = 5
# Tier 3 #14 — keep more members than other top-N lists so a busier
# workspace's members are all in the chunk (a 12-person nonprofit
# shouldn't get truncated to 5).
TOP_MEMBERS_N = 10


def _iso(value) -> str:
    if not value:
        return ""
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _str_values(queryset, field: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in queryset.values_list(field, flat=True) if value)


class DjangoWorkspaceSnapshotDataAdapter(WorkspaceSnapshotDataPort):
    """Reads ``Workspace`` + related rows and returns a plain dataclass."""

    def load(self, workspace_id: str) -> WorkspaceSnapshotInput | None:
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = (
            Workspace.objects.select_related("sector")
            .prefetch_related(
                "workspace_categories",
                "workspace_subcategories",
                "tags",
                "operations",
                "contribution_means",
            )
            .filter(id=workspace_id)
            .first()
        )
        if workspace is None:
            return None

        sector_name = ""
        if workspace.sector_id:
            sector_name = (
                getattr(workspace.sector, "name", None)
                or getattr(workspace.sector, "slug", None)
                or str(workspace.sector_id)
            )

        from infrastructure.persistence.team.models import Team

        member_count = workspace.memberships.count()
        active_member_count = workspace.memberships.filter(status="active").count()
        follower_count = workspace.followers.count()
        team_count = Team.objects.filter(workspace_id=workspace.id).count()

        cutoff = timezone.now() - timedelta(days=RECENT_ACTIVITY_DAYS)
        activity = _load_recent_activity(workspace.id, cutoff)
        top_entities = _load_top_entities(workspace.id)
        top_members = _load_top_members(workspace.id)

        return WorkspaceSnapshotInput(
            workspace_id=str(workspace.id),
            workspace_name=workspace.workspace_name or "",
            workspace_type=workspace.workspace_type or "",
            sector_name=sector_name,
            story=workspace.workspace_story or "",
            vision=workspace.vision or "",
            mission=workspace.mission or "",
            privacy=workspace.privacy or "",
            status=workspace.status or "",
            default_currency=workspace.default_currency or "",
            contact_email=workspace.contact_email or "",
            categories=_str_values(workspace.workspace_categories.all(), "name"),
            subcategories=_str_values(workspace.workspace_subcategories.all(), "name"),
            tags=_str_values(workspace.tags.all(), "name"),
            operations=_str_values(workspace.operations.all(), "name"),
            contribution_means=_str_values(workspace.contribution_means.all(), "name"),
            member_count=member_count,
            active_member_count=active_member_count,
            follower_count=follower_count,
            team_count=team_count,
            recent_new_grant_decision_count_30d=activity["new_grant_decision_count"],
            recent_new_project_count_30d=activity["new_project_count"],
            open_grants=top_entities["open_grants"],
            active_projects=top_entities["active_projects"],
            top_members=top_members,
            created_at_iso=_iso(workspace.created_at),
            updated_at_iso=_iso(workspace.updated_at),
        )


def _load_recent_activity(workspace_id, cutoff) -> dict:
    """Run the five recent-activity queries.  Each is wrapped so one
    schema change can't blank the others — failure to load a domain
    just drops that line from the section body."""
    result = {
        "new_grant_decision_count": 0,
        "new_project_count": 0,
    }
    try:
        from infrastructure.persistence.workspaces.models import Grant

        # Approximation: count Grants whose row was modified inside the
        # window.  GrantDecision is the canonical per-stage event log
        # but the snapshot doesn't need that granularity — the count of
        # touched grants is the signal.
        result["new_grant_decision_count"] = Grant.objects.filter(
            workspace_id=workspace_id, updated_at__gte=cutoff
        ).count()
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "snapshot: failed to load grant decision count workspace_id=%s",
            workspace_id,
        )
    try:
        from infrastructure.persistence.project.models import Project

        result["new_project_count"] = Project.objects.filter(workspace_id=workspace_id, created_at__gte=cutoff).count()
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "snapshot: failed to load project count workspace_id=%s",
            workspace_id,
        )
    return result


def _load_top_entities(workspace_id) -> dict:
    """Run the top-N queries.  Same defensive-per-domain pattern
    as ``_load_recent_activity``."""
    result = {
        "open_grants": (),
        "active_projects": (),
    }
    try:
        from infrastructure.persistence.workspaces.models import Grant

        open_stages = (
            "researching",
            "loi",
            "invited",
            "drafting",
            "submitted",
            "under_review",
        )
        rows = Grant.objects.filter(workspace_id=workspace_id, pipeline_stage__in=open_stages).order_by(
            "submission_deadline"
        )[:TOP_N]
        result["open_grants"] = tuple(
            (getattr(g, "funder_name", "") or "grant")
            + f" — {getattr(g, 'pipeline_stage', '') or 'open'}"
            + (f", due {g.submission_deadline.isoformat()}" if getattr(g, "submission_deadline", None) else "")
            for g in rows
        )
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "snapshot: failed to load open grants workspace_id=%s",
            workspace_id,
        )
    try:
        from infrastructure.persistence.project.models import Project

        rows = (
            Project.objects.filter(workspace_id=workspace_id)
            .exclude(status="completed")
            .exclude(status="archived")
            .order_by("-created_at")[:TOP_N]
        )
        result["active_projects"] = tuple(
            f"{getattr(p, 'title', '') or 'project'} — {getattr(p, 'status', '') or 'active'}" for p in rows
        )
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "snapshot: failed to load active projects workspace_id=%s",
            workspace_id,
        )
    return result


def _load_top_members(workspace_id) -> tuple[str, ...]:
    """Tier 3 #14 — load active workspace members by name + role.

    Closes the "Find <person>" routing gap by giving hybrid search a
    chunk that names the workspace's actual members.  Without this,
    bare "Find <name>" queries were pulled toward donation_agent
    because top donors were the only named identities in the
    embedding index.

    Returns rows pre-formatted as ``"First Last — Role"``.  Email is
    intentionally NOT included — PII stays out of the embedding
    index; ``user_agent.get_user_profile`` owns email lookup.

    Falls back to an empty tuple on any failure (consistent with the
    rest of the adapter's per-domain defensive pattern).
    """
    try:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        rows = (
            WorkspaceMembership.objects.filter(workspace_id=workspace_id, status="active")
            .select_related("user", "workspace_role")
            .order_by("-created_at")[:TOP_MEMBERS_N]
        )
        formatted: list[str] = []
        for m in rows:
            user = m.user
            first = (getattr(user, "first_name", "") or "").strip()
            last = (getattr(user, "last_name", "") or "").strip()
            name = (f"{first} {last}").strip() or (getattr(user, "username", "") or f"member {m.user_id}")
            role = ""
            if m.workspace_role_id:
                role = (getattr(m.workspace_role, "name", "") or getattr(m.workspace_role, "slug", "") or "").strip()
            if not role:
                role = (m.role or "").strip()
            row = f"{name} — {role}" if role else name
            formatted.append(row)
        return tuple(formatted)
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "snapshot: failed to load top members workspace_id=%s",
            workspace_id,
        )
        return ()
