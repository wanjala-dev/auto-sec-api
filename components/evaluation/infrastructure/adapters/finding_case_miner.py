"""Mine a workspace's own decisions into eval cases (ADR 0033 D3).

Reads the two sources that actually carry human judgement in this product:

- a **suppressed** finding — someone decided it was not worth acting on
- a **resolved** finding — someone decided it was, and it got fixed

Both go through ``case_diversity.collapse_to_distinct`` FIRST, and that is the
point of this module rather than an implementation detail. Measured on the live
demo workspace: 1,646 suppressions, of which 1,645 share one reason string and
one minute — a single bulk cleanup. Counting rows would have produced a suite
of 1,645 identical cases and a pass rate over a denominator of 1,645.
"""

from __future__ import annotations

import logging

from components.evaluation.domain.services.case_diversity import (
    DecisionRecord,
    availability,
    collapse_to_distinct,
)

logger = logging.getLogger(__name__)

#: Statuses that represent a human decision we can learn from.
_LABEL_BY_STATUS = {
    "suppressed": "bad",
    "resolved": "good",
}


def _records_for(workspace_id: str, *, limit: int = 5000) -> list[DecisionRecord]:
    from infrastructure.persistence.findings.models import Finding

    rows = (
        Finding.objects.filter(workspace_id=workspace_id, status__in=list(_LABEL_BY_STATUS))
        .order_by("-resolved_at")
        .values("id", "status", "status_reason", "resolved_at", "title", "severity", "source", "asset_urn")[:limit]
    )
    return [
        DecisionRecord(
            source_ref=str(row["id"]),
            source_kind="finding",
            reason=row["status_reason"] or "",
            decided_at=row["resolved_at"],
            label=_LABEL_BY_STATUS.get(row["status"], "unlabelled"),
            payload={
                "title": row["title"],
                "severity": row["severity"],
                "source": row["source"],
                "asset_urn": row["asset_urn"],
            },
        )
        for row in rows
    ]


def workspace_availability(workspace_id: str, *, required: int):
    """What could be mined right now — raw rows AND distinct decisions."""
    return availability(_records_for(workspace_id), required=required)


def mine_cases(*, workspace_id: str, suite, limit: int | None = None) -> dict:
    """Create one EvalCase per DISTINCT decision. Idempotent.

    Re-running adds only decisions not already present: the unique constraint
    on (suite, source_kind, source_ref) is the guard, so a second mine of the
    same history does not inflate the suite.
    """
    from infrastructure.persistence.evaluation.models import EvalCase

    distinct = collapse_to_distinct(_records_for(workspace_id))
    if limit is not None:
        distinct = distinct[:limit]

    created = skipped = 0
    for decision in distinct:
        representative = decision.representative
        _, was_created = EvalCase.objects.get_or_create(
            suite=suite,
            source_kind=EvalCase.SourceKind.FINDING,
            source_ref=representative.source_ref,
            defaults={
                "workspace_id": workspace_id,
                "scenario": decision.scenario,
                "prompt_inputs": representative.payload,
                # The reviewer's own rationale IS the criterion for this case —
                # what "right" meant here, in their words, rather than a
                # generic standard a judge would otherwise invent (D10).
                "solution_criteria": (
                    [f"Matches the reviewer's decision: {representative.reason}"] if representative.reason else []
                ),
                "label": representative.label,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    logger.info(
        "eval_cases_mined workspace=%s suite=%s distinct=%s created=%s existing=%s",
        workspace_id,
        suite.id,
        len(distinct),
        created,
        skipped,
    )
    return {"distinct": len(distinct), "created": created, "already_present": skipped}


__all__ = ["mine_cases", "workspace_availability"]
