"""Build the ATT&CK coverage heatmap from a workspace's findings — pure aggregation.

Given each open finding's ATT&CK technique ids (from ``compliance["MITRE ATT&CK"]``)
and severity, produce the heatmap: techniques grouped by tactic (kill-chain order),
each with a finding count + the worst severity seen. Framework-free and deterministic
so it's exhaustively unit-testable; the heavy DB read + the caching live in the
adapter/use case, never here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from components.shared_kernel.domain.mitre import TECHNIQUES

# Worst-first severity ranking for a technique's ``max_severity`` rollup.
_SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1, "": 0}


def _worse(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


def build_attck_coverage(entries: Iterable[tuple[Sequence[str], str]]) -> dict:
    """entries = ``(technique_ids, severity)`` per open finding carrying ATT&CK tags.

    Returns ``{"tactics": [...], "totals": {...}}`` — the materialized heatmap blob.
    """
    # technique_id -> {count, max_severity}
    per_technique: dict[str, dict] = {}
    contributing_findings = 0

    for technique_ids, severity in entries:
        matched = [tid for tid in technique_ids if tid in TECHNIQUES]
        if not matched:
            continue
        contributing_findings += 1
        for tid in matched:
            row = per_technique.setdefault(tid, {"finding_count": 0, "max_severity": ""})
            row["finding_count"] += 1
            row["max_severity"] = _worse(row["max_severity"], severity or "")

    # Group techniques under their tactic.
    by_tactic: dict[str, list[dict]] = {}
    for tid, agg in per_technique.items():
        tech = TECHNIQUES[tid]
        by_tactic.setdefault(tech.tactic.value, []).append(
            {
                "technique_id": tech.technique_id,
                "name": tech.name,
                "url": tech.url,
                "finding_count": agg["finding_count"],
                "max_severity": agg["max_severity"] or "info",
            }
        )

    tactics = []
    for tactic_value, techniques in by_tactic.items():
        tactic = _tactic_of(tactic_value)
        techniques.sort(key=lambda t: (-t["finding_count"], t["technique_id"]))
        tactics.append(
            {
                "tactic": tactic_value,
                "label": tactic.label,
                "order": tactic.order,
                "techniques": techniques,
            }
        )
    tactics.sort(key=lambda t: t["order"])

    return {
        "tactics": tactics,
        "totals": {
            "techniques": len(per_technique),
            "findings": contributing_findings,
            "tactics": len(tactics),
        },
    }


def _tactic_of(value: str):
    from components.shared_kernel.domain.mitre import MitreTactic

    return MitreTactic(value)
