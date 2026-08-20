"""Adapter: read report findings from the Finding SSOT, board state joined on.

Implements :class:`FindingSourcePort`. **The SSOT is the spine; board state is
enrichment.** Every finding the workspace holds is a report candidate — including
the ones the board's severity floor never let through (ADR 0019 D4) and the whole
source classes that are deliberately SSOT-only (ADR 0021 D4). The board card,
when one exists, contributes what it genuinely owns: the column, the team, the
assignees and the triage decision — "and here's what we did about it". A finding
with no card is not dropped; it is returned and explicitly marked **untriaged**.

Query budget (perf rule §1 — constant, never scaling with row count):

1. ONE aggregate for the whole accounting (matched / resolved / suppressed /
   sample counts) — so every exclusion is a stated number, not a silent drop.
2. ONE indexed read of the findings page.
3. ONE read of the board cards for exactly those finding ids.
4. ONE prefetch of those cards' assignees.
5. ONE aggregate over ``ScanRun`` for the scope's scan coverage — so an empty
   report can say whether anything looked, rather than reading as a clean result.

Reading ``infrastructure.persistence.{findings,project}.models`` is a persistence
read, NOT a ``components.<ctx>.infrastructure`` import — it does not cross the
component-infrastructure boundary the architecture tests guard. This is the same
sanctioned cross-context read pattern ``findings`` itself uses to reach the board
(``BoardTriageStateRepository``) and ``remediation`` uses to reach it for facts.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from django.db.models import Case, Count, IntegerField, Max, Q, When

from components.report.application.ports.finding_source_port import (
    FindingPage,
    FindingQuery,
    FindingSourcePort,
)
from components.report.domain.value_objects.scan_coverage import ScanCoverage
from components.shared_kernel.domain.security import SAMPLE_SOURCE_PREFIX, FindingStatus, Severity

logger = logging.getLogger(__name__)

#: Statuses a report never lists unless the kind opts in. Both are terminal, and
#: both are counted and surfaced rather than silently omitted (see
#: ``FindingPage.excluded_*``): a suppressed finding is an *accepted risk*, which
#: an auditor wants stated, not hidden; a resolved finding is "what we closed
#: this period", which is a fact about the period, not a live vulnerability.
_SUPPRESSED = FindingStatus.SUPPRESSED.value
_RESOLVED = FindingStatus.RESOLVED.value

#: Board cards carry their finding's id at ``metadata.payload.finding_id``
#: (written by every ``_build_*_card`` in ``finding_raised_board_handler`` and
#: nested under ``payload`` by ``persist_finding_as_task``). Same join key the
#: findings context uses for its own triage-state read.
_BOARD_FINDING_ID_PATH = "metadata__payload__finding_id__in"

#: How many raw ``attributes`` entries get promoted into the evidence block. The
#: block is a printed artifact, not a JSON dump — enough to ground the finding,
#: bounded so one verbose scanner cannot blow out a page.
_MAX_ATTRIBUTE_EVIDENCE = 8

#: Attribute keys that are structure, not evidence — already rendered elsewhere
#: on the section (or reproduced deliberately nowhere, per ADR 0019 D8).
_ATTRIBUTE_EVIDENCE_SKIP = frozenset(
    {
        "board_payload",
        "board_context",
        "agent_type",
        "impact_score",
        "snippet",  # matched source region — never re-printed into a deliverable
        "legs",
        "attack_flow",
    }
)


def _severity_rank_ordering():
    """Order most-severe-first.

    ``Finding.severity`` is a CharField, so a plain ``order_by`` would sort
    alphabetically ("critical" < "high" < "informational" < "low" < "medium") —
    which is not severity order at all. The rank is projected explicitly. This
    trades the ``(workspace, severity, -last_seen_at)`` index's ordering for a
    sort over the workspace's scoped findings, which is the right trade: when
    ``limit`` truncates, a report MUST keep its criticals.
    """
    return Case(
        *[When(severity=sev.value, then=-sev.rank) for sev in Severity],
        default=1,  # unknown band sorts last, never above a real critical
        output_field=IntegerField(),
    )


class SsotFindingRepository(FindingSourcePort):
    def list_findings(self, query: FindingQuery) -> FindingPage:
        from infrastructure.persistence.findings.models import Finding

        scoped = self._apply_window(
            self._apply_source_scope(
                Finding.objects.filter(workspace_id=query.workspace_id),
                query,
            ),
            query,
        )

        include_q = self._inclusion_filter(query)

        # (1) One aggregate: the full accounting. Every number a report needs to
        #     be honest about what it is NOT showing comes from this single pass.
        counts = scoped.aggregate(
            matched=Count("id", filter=include_q),
            resolved=Count("id", filter=Q(status=_RESOLVED)),
            suppressed=Count("id", filter=Q(status=_SUPPRESSED)),
            sample=Count("id", filter=Q(source__startswith=SAMPLE_SOURCE_PREFIX)),
        )
        total_matched = int(counts["matched"] or 0)

        # (2) One indexed read of the page, most-severe first.
        rows = list(
            scoped.filter(include_q)
            .annotate(_severity_rank=_severity_rank_ordering())
            .order_by("_severity_rank", "-last_seen_at", "id")[: max(1, int(query.limit))]
        )

        # (3)+(4) One board read for exactly these findings + one assignee prefetch.
        enrichment = self._board_enrichment(
            workspace_id=query.workspace_id,
            finding_ids=[str(row.id) for row in rows],
        )

        findings = tuple(self._to_mapping(row, enrichment.get(str(row.id))) for row in rows)
        sample_count = sum(1 for f in findings if f["is_sample"])

        page = FindingPage(
            findings=findings,
            total_matched=total_matched,
            excluded_resolved=0 if query.include_resolved else int(counts["resolved"] or 0),
            excluded_suppressed=0 if query.include_suppressed else int(counts["suppressed"] or 0),
            excluded_sample=0 if query.include_sample else int(counts["sample"] or 0),
            sample_count=sample_count,
            # (5) One aggregate over the scan-execution store: did anything
            #     actually look? Zero findings alone cannot answer that, and a
            #     deliverable that treats "nothing scanned" as "nothing found"
            #     is the falsehood this read exists to prevent.
            scan_coverage=self._scan_coverage(query),
        )
        logger.info(
            "report.ssot_findings_read workspace_id=%s returned=%d matched=%d truncated=%d "
            "untriaged=%d sample=%d excluded_resolved=%d excluded_suppressed=%d "
            "scans_completed=%d scans_failed=%d scans_running=%d",
            query.workspace_id,
            page.returned_count,
            page.total_matched,
            page.truncated_count,
            sum(1 for f in findings if not f["triage"]["on_board"]),
            sample_count,
            page.excluded_resolved,
            page.excluded_suppressed,
            page.scan_coverage.completed_runs,
            page.scan_coverage.failed_runs,
            page.scan_coverage.running_runs,
        )
        return page

    # ── scan coverage ────────────────────────────────────────────────────

    @staticmethod
    def _scan_coverage(query: FindingQuery) -> ScanCoverage:
        """Did a scan actually cover this report's scope and period?

        ONE aggregate over ``ScanRun`` — the generic scan-execution store every
        pillar writes (``ScanRun.source`` matches the ``Finding.source`` of the
        findings it emits, so the report's own source scope applies verbatim).

        This is the difference between "we looked and the estate is clean" and
        "nothing has ever looked", which a finding count of zero cannot express.
        The window is the run's own ``created_at``: a scan that ran before the
        period does not cover the period, however clean its result was.
        """
        from infrastructure.persistence.scanning.models import ScanRun

        runs = ScanRun.objects.filter(workspace_id=query.workspace_id)
        for names in (query.source_prefixes, query.sources):
            if not names:
                continue
            match = Q()
            for name in names:
                cleaned = str(name).strip()
                if cleaned:
                    match |= Q(source__startswith=cleaned)
            if match:
                runs = runs.filter(match)
        if query.since is not None:
            runs = runs.filter(created_at__gte=query.since)
        if query.until is not None:
            runs = runs.filter(created_at__lte=query.until)

        agg = runs.aggregate(
            completed=Count("id", filter=Q(status=ScanRun.Status.COMPLETED)),
            failed=Count("id", filter=Q(status=ScanRun.Status.FAILED)),
            running=Count("id", filter=Q(status__in=(ScanRun.Status.RUNNING, ScanRun.Status.PENDING))),
            last_completed=Max("completed_at", filter=Q(status=ScanRun.Status.COMPLETED)),
        )
        return ScanCoverage(
            completed_runs=int(agg["completed"] or 0),
            failed_runs=int(agg["failed"] or 0),
            running_runs=int(agg["running"] or 0),
            last_completed_at=agg["last_completed"],
        )

    # ── scoping ──────────────────────────────────────────────────────────

    @staticmethod
    def _apply_source_scope(qs, query: FindingQuery):
        """Kind prefixes AND the operator's allow-list, both prefix-matched.

        Prefix rather than exact match so ``cloud_posture`` selects
        ``cloud_posture.prowler`` and ``cloud_posture.prowler.vercel`` alike — an
        operator scoping to a pillar means the pillar, not one engine of it.
        """
        for names in (query.source_prefixes, query.sources):
            if not names:
                continue
            match = Q()
            for name in names:
                cleaned = str(name).strip()
                if cleaned:
                    match |= Q(source__startswith=cleaned)
            if match:
                qs = qs.filter(match)
        return qs

    @staticmethod
    def _apply_window(qs, query: FindingQuery):
        """The finding was live at some point inside [since, until]."""
        if query.until is not None:
            qs = qs.filter(first_seen_at__lte=query.until)
        if query.since is not None:
            qs = qs.filter(Q(resolved_at__isnull=True) | Q(resolved_at__gte=query.since))
        return qs

    @staticmethod
    def _inclusion_filter(query: FindingQuery) -> Q:
        include = Q()
        if not query.include_resolved:
            include &= ~Q(status=_RESOLVED)
        if not query.include_suppressed:
            include &= ~Q(status=_SUPPRESSED)
        if not query.include_sample:
            include &= ~Q(source__startswith=SAMPLE_SOURCE_PREFIX)
        return include

    # ── board enrichment ─────────────────────────────────────────────────

    @staticmethod
    def _board_enrichment(*, workspace_id: str, finding_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """``{finding_id: triage-state}`` for the page, in ONE query pass.

        A finding absent from the result simply has no card — the caller marks it
        untriaged. Never a per-finding lookup: this feeds a whole report.
        """
        if not finding_ids:
            return {}

        from infrastructure.persistence.project.models import Task

        cards = (
            Task.objects.filter(workspace_id=workspace_id, **{_BOARD_FINDING_ID_PATH: list(finding_ids)})
            .select_related("column", "team")
            .prefetch_related("assigned_to")
        )

        enrichment: dict[str, dict[str, Any]] = {}
        for card in cards:
            metadata = card.metadata or {}
            finding_id = str((metadata.get("payload") or {}).get("finding_id") or "")
            if not finding_id:
                continue
            enrichment[finding_id] = {
                "on_board": True,
                "task_id": str(card.id),
                "source_type": card.source_type or "",
                "column": (card.column.title if card.column else ""),
                "team": (card.team.title if card.team else ""),
                "task_status": card.status or "",
                "triage_status": str((metadata.get("triage") or {}).get("status") or ""),
                "assignees": sorted((user.username or user.email or "") for user in card.assigned_to.all()),
            }
        return enrichment

    # ── mapping ──────────────────────────────────────────────────────────

    @classmethod
    def _to_mapping(cls, row, triage: dict[str, Any] | None) -> Mapping[str, Any]:
        attributes = row.attributes or {}
        compliance = row.compliance or {}
        is_sample = str(row.source or "").startswith(SAMPLE_SOURCE_PREFIX)
        board = triage or {"on_board": False}

        return {
            "id": str(row.id),
            "title": row.title or "",
            "description": row.description or "",
            "severity": row.severity or "",
            "status": row.status or "",
            "source": row.source or "",
            "source_type": board.get("source_type", ""),
            # Curation + ordering read ``created_at``; for a finding, "created"
            # is its first observation, not the moment a card happened to appear.
            "created_at": row.first_seen_at,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "resolved_at": row.resolved_at,
            "is_sample": is_sample,
            # The SSOT already deduped on (workspace, source, fingerprint), so the
            # assembler must NOT re-collapse these by fuzzy title — that would
            # merge genuinely distinct findings and undercount, the exact sin this
            # adapter exists to end. An exact key switches curation to identity.
            "dedup_key": f"{row.source}|{row.fingerprint}",
            "metadata": {
                "severity": row.severity or "",
                "action_type": row.source or "",
                "detector": row.source or "",
                "ai_headline": row.title or "",
                "ai_narrative": row.description or "",
                "asset_urn": row.asset_urn or "",
                "compliance": compliance,
                "payload": {
                    "asset_urn": row.asset_urn or "",
                    "signal": row.title or "",
                    "confidence": str(attributes.get("confidence") or ""),
                    "recommendation": row.remediation or "",
                    "evidence": cls._evidence(row, attributes, compliance),
                },
            },
            "triage": board,
        }

    @staticmethod
    def _evidence(row, attributes: Mapping[str, Any], compliance: Mapping[str, Any]) -> list[dict[str, str]]:
        """Evidence lines built from the SSOT's own columns — grounded, no invention."""
        lines: list[dict[str, str]] = [
            {"type": "asset", "detail": row.asset_urn or "not specified"},
            {"type": "source", "detail": row.source or "unknown"},
            {"type": "fingerprint", "detail": row.fingerprint or ""},
        ]
        if row.first_seen_at:
            lines.append({"type": "first seen", "detail": row.first_seen_at.isoformat()})
        if row.last_seen_at:
            lines.append({"type": "last seen", "detail": row.last_seen_at.isoformat()})
        if row.scan_run_id:
            lines.append({"type": "scan run", "detail": str(row.scan_run_id)})
        for framework, controls in sorted((compliance or {}).items()):
            rendered = ", ".join(str(c) for c in controls) if isinstance(controls, (list, tuple)) else str(controls)
            lines.append({"type": str(framework), "detail": rendered})

        promoted = 0
        for key, value in sorted((attributes or {}).items()):
            if promoted >= _MAX_ATTRIBUTE_EVIDENCE:
                break
            if key in _ATTRIBUTE_EVIDENCE_SKIP or isinstance(value, (dict, list, tuple)):
                continue
            rendered = str(value).strip()
            if not rendered:
                continue
            lines.append({"type": str(key), "detail": rendered})
            promoted += 1
        return lines
