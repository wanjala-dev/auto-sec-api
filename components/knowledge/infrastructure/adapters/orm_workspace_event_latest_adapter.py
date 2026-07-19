"""ORM adapter for the ``WorkspaceEventLatestPort``.

Walks every model that has a signal bridge wired in
``WorkspaceIndexSignalProvider`` and returns the most recent
event time across all of them. Each domain's query lives in its own
try/except so a schema change in one domain (e.g. ``Project``
gaining a new ``updated_at`` quirk) can't blank the others — the
adapter degrades to "I can read 7 of 8 sources" rather than "I
can read nothing."

Adding a new signal bridge MUST also add the same model here,
otherwise the SLO under-reports lag for changes to that model
(events fire reindex but the audit doesn't see the trigger source).

Tier 3 #14 audit. See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db.models import Max

from components.knowledge.application.ports.workspace_event_latest_port import (
    WorkspaceEventLatestPort,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceEventLatestAdapter(WorkspaceEventLatestPort):
    """Concrete adapter — one ORM query per watched domain.

    Returns ``max`` across the per-domain results, treating ``None``
    as "this domain has no rows for the workspace" (skipped, not
    treated as zero).
    """

    def latest_event_time(self, *, workspace_id: str) -> datetime | None:
        if not workspace_id:
            return None

        # Per-source timestamp field map. Each tuple is
        # (domain_label, model dotted path, latest timestamp field
        # name, pk-vs-FK filter mode). Field names differ across
        # contexts because some models inherit from StandardMetadata
        # (updated_at) and others only ship created_at — verified
        # against the actual field set on each model during the
        # 2026-06-11 audit. Don't substitute a "common" field
        # without re-checking: a model that doesn't have the column
        # surfaces as a FieldError, which the per-source try/except
        # below swallows but turns into "this domain reports
        # nothing" — silent under-reporting of lag.
        sources: list[tuple[str, str, str, bool]] = [
            (
                "workspace",
                "infrastructure.persistence.workspaces.models.Workspace",
                "updated_at",
                True,  # pk-filter — Workspace is its own primary key
            ),
            (
                "grant",
                "infrastructure.persistence.workspaces.models.Grant",
                "updated_at",
                False,
            ),
            (
                "project",
                "infrastructure.persistence.project.models.Project",
                "created_at",
                False,
            ),
            (
                "team",
                "infrastructure.persistence.team.models.Team",
                "created_at",
                False,
            ),
            (
                "workspace_membership",
                "infrastructure.persistence.workspaces.models.WorkspaceMembership",
                "updated_at",
                False,
            ),
        ]

        latest: datetime | None = None
        for domain_label, dotted, field, pk_filter in sources:
            try:
                value = self._max_field(
                    dotted,
                    workspace_id,
                    field=field,
                    pk_filter=pk_filter,
                )
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "knowledge: SLO audit failed to read latest event for domain=%s workspace_id=%s — skipping",
                    domain_label,
                    workspace_id,
                )
                continue
            if value is None:
                continue
            if latest is None or value > latest:
                latest = value
        return latest

    @staticmethod
    def _max_field(
        dotted: str,
        workspace_id: str,
        *,
        field: str,
        pk_filter: bool = False,
    ) -> datetime | None:
        """Lazy-load the model + run ``Max(field)``.

        ``pk_filter`` is for the Workspace row itself — filter by id,
        not workspace_id. Every other watched model has a
        ``workspace_id`` FK; Workspace is its own primary key.

        Returns ``None`` if the queryset is empty (model exists but
        no rows for this workspace) or if the field is missing
        (catches schema drift loudly via ``FieldError``).
        """
        from importlib import import_module

        module_path, class_name = dotted.rsplit(".", 1)
        model = getattr(import_module(module_path), class_name)
        if pk_filter:
            qs = model.objects.filter(pk=workspace_id)
        else:
            qs = model.objects.filter(workspace_id=workspace_id)
        return qs.aggregate(latest=Max(field))["latest"]
