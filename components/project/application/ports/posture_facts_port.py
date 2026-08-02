"""Port: read the board-finding facts the security-posture aggregates need.

The ``project`` context owns ``Task``; the ``agents`` posture services
(``posture_service`` / ``posture_dashboard_service``) compute every posture
number from board findings that already exist on ``project.Task``. Today they do
that through direct ``infrastructure.persistence.project.models`` reads inside
the application layer. This port is the sanctioned read seam so those
aggregations depend on a ``project`` interface, not ``project``'s ORM
(architecture-skill C3 / Rule 2: read another context's data through a port).

It exposes exactly the two board reads the posture aggregates make, both
workspace-scoped (tenant isolation) and both excluding the posture report's own
board card (``ai.posture_report``) so the weekly report can never count itself:

1. ``collect_finding_facts`` — the ``_collect_finding_rows`` read: every OPEN
   AI-finding card (a stock) UNION every AI-finding card TOUCHED inside the
   window (flow candidates), deduped by id. Returns one :class:`PostureFinding`
   per task. The pure ``compute_*`` functions in ``posture_service`` do the
   precise open/triaged/toil classification off these DTOs — this port only
   supplies the rows.

2. ``count_findings_created`` — the ``forward_outlook`` read: how many
   AI-finding cards were CREATED in a ``[since, until)`` half-open window (used
   for the this-week vs last-week creation delta).

3. ``count_findings_created_by_date`` — the ``posture_dashboard_service``
   read: AI-finding cards created since an instant, bucketed by their creation
   calendar day (ISO date → count), for the dashboard's findings-per-day chart
   series. Returns ``(by_date, present)`` — ``present`` distinguishes "no rows"
   from "an all-zero calendar" so the dashboard's ``no_data`` honesty holds.

Returning frozen DTOs (never ORM instances) keeps the ORM behind the seam; the
DTO fields mirror the exact keys ``posture_service._finding_row`` builds today so
the consumer swap is a straight substitution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PostureFinding:
    """One board-finding row as the posture aggregates consume it.

    Field-for-field the dict ``posture_service._finding_row`` builds today:

    * ``created_at`` is the aware DB datetime (posture math windows on it).
    * ``triaged_at`` / ``first_action_at`` are raw stored values off
      ``metadata`` (naive/aware ISO strings) — the consumer's ``_parse_iso``
      normalizes them; this port passes them through untouched.
    * ``kind`` is the ``source_type`` (e.g. ``ai.log_watch``), matching the
      consumer's ``"kind"`` key.
    """

    id: str
    severity: str
    kind: str
    status: str
    created_at: datetime
    triage_status: str | None
    triaged_at: Any
    needs_human: bool
    agent: str
    rubric_verdict: str | None
    first_action_at: Any


class PostureFactsPort(ABC):
    @abstractmethod
    def collect_finding_facts(self, *, workspace_id: str, window_start: datetime) -> list[PostureFinding]:
        """Board findings relevant to posture for a workspace.

        Every OPEN AI-finding card (``status='todo'``, a stock measured at now)
        UNION every AI-finding card whose ``updated_at`` is at/after
        ``window_start`` (flow candidates), deduped by id. Excludes the posture
        report's own card. Workspace-scoped — no cross-workspace leak.
        """

    @abstractmethod
    def count_findings_created(self, *, workspace_id: str, since: datetime, until: datetime | None = None) -> int:
        """Count AI-finding cards created in ``[since, until)`` for a workspace.

        Half-open window: ``created_at >= since`` and, when ``until`` is given,
        ``created_at < until``. Excludes the posture report's own card.
        Workspace-scoped.
        """

    @abstractmethod
    def count_findings_created_by_date(self, *, workspace_id: str, since: datetime) -> tuple[dict[str, int], bool]:
        """AI-finding cards created ``>= since``, bucketed by creation ISO date.

        Returns ``(by_date, present)`` where ``by_date`` maps ``YYYY-MM-DD`` →
        count (only days that HAVE cards appear) and ``present`` is True iff any
        card matched. Excludes the posture report's own card. Workspace-scoped.
        """
