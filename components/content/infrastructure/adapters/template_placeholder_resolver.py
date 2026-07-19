"""Resolve ``{{placeholder}}`` patterns in template body_html.

When a user "Use this template"s a seeded template, the body lands in
the editor with placeholders like ``{{recipient_count}}`` and
``{{donations_total}}``. We resolve workspace-derived placeholders
inline so the user opens the editor with real numbers already filled
in. User-context placeholders (``{{funder_name}}``,
``{{recipient_name}}`` etc.) intentionally remain literal — the editor
highlights them so the user fills in the rest.

Known placeholder set (extend here as templates grow):

    {{workspace_name}}        — name of the active workspace
    {{donations_count}}       — # donations in the last 30 days
    {{donations_total}}       — formatted sum of donations
    {{recipient_count}}       — total active recipients
    {{new_recipients}}        — recipients created in the last 30 days
    {{upcoming_events_count}} — events in the upcoming 30 days
    {{program_count}}         — total projects/programs
    {{date}}                  — today's date (ISO)
    {{year}}                  — current year

Anything not in the set is left alone — the editor highlights it.
"""

from __future__ import annotations

import datetime
import logging
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _format_currency(value: Decimal | float | int) -> str:
    try:
        amount = Decimal(value or 0)
    except (TypeError, ValueError):
        amount = Decimal(0)
    return f"${amount:,.0f}"


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _build_workspace_context(workspace_id: UUID) -> dict[str, Any]:
    """Look up all workspace-derived placeholder values in one pass.

    Each section is wrapped in try/except so a broken sub-query never
    poisons the whole resolution. Missing values fall through to ``''``
    when substituted.
    """
    ctx: dict[str, Any] = {
        "date": _today_iso(),
        "year": str(datetime.date.today().year),
    }

    # Workspace name. The Workspace model uses ``workspace_name`` (the
    # admin-typed display name); ``name`` is a legacy alias that some
    # callers still reference but the field is gone from the schema.
    try:
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = (
            Workspace.objects.filter(pk=workspace_id)
            .only("workspace_name")
            .first()
        )
        if workspace is not None:
            ctx["workspace_name"] = workspace.workspace_name or ""
    except Exception:  # noqa: BLE001
        logger.exception(
            "placeholder resolver: workspace name lookup failed for %s",
            workspace_id,
        )

    # Donations — count + total over the last 30 days
    try:
        from django.db.models import Sum
        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        since = datetime.date.today() - datetime.timedelta(days=30)
        qs = Donation.objects.filter(
            workspace_id=workspace_id,
            created_at__date__gte=since,
        )
        agg = qs.aggregate(total=Sum("amount"))
        ctx["donations_count"] = str(qs.count())
        ctx["donations_total"] = _format_currency(agg.get("total") or 0)
    except Exception:  # noqa: BLE001
        logger.exception(
            "placeholder resolver: donations lookup failed for %s", workspace_id
        )

    # Recipients
    try:
        from infrastructure.persistence.sponsorship.recipients.models import (
            Recipient,
        )

        since = datetime.date.today() - datetime.timedelta(days=30)
        ctx["recipient_count"] = str(
            Recipient.objects.filter(workspace_id=workspace_id).count()
        )
        ctx["new_recipients"] = str(
            Recipient.objects.filter(
                workspace_id=workspace_id, created_at__date__gte=since
            ).count()
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "placeholder resolver: recipients lookup failed for %s", workspace_id
        )

    # Upcoming events — Event has ``start_date`` (a DateTimeField), not
    # ``date``. Compare against today's midnight for ``__gte`` rather than
    # the value itself so the filter normalises across timezone boundaries.
    try:
        from infrastructure.persistence.sponsorship.events.models import Event

        ctx["upcoming_events_count"] = str(
            Event.objects.filter(
                workspace_id=workspace_id,
                start_date__date__gte=datetime.date.today(),
            ).count()
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "placeholder resolver: events lookup failed for %s", workspace_id
        )

    # Programs / projects
    try:
        from infrastructure.persistence.project.models import Project

        ctx["program_count"] = str(
            Project.objects.filter(workspace_id=workspace_id).count()
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "placeholder resolver: project count lookup failed for %s",
            workspace_id,
        )

    return ctx


class TemplatePlaceholderResolver:
    """Stateless service: substitute known placeholders in a body string."""

    def resolve(self, *, body_html: str, workspace_id: UUID) -> str:
        if not body_html:
            return body_html
        if "{{" not in body_html:
            return body_html

        try:
            context = _build_workspace_context(workspace_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "placeholder resolver: full context build failed; returning raw body"
            )
            return body_html

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            # Known key → substitute. Unknown key → leave literal so the
            # editor highlights it for the user to fill.
            if key in context:
                return str(context[key])
            return match.group(0)

        return _PLACEHOLDER_RE.sub(replace, body_html)
