"""Read model for the HUD CLOUD POSTURE card — served by the spine (audit R2).

Aggregates the latest completed ``ScanRun`` + OPEN Finding-SSOT counts per
scanned account for a workspace. The legacy per-pillar snapshot tables
(``CloudPostureScan``/``CloudPostureFinding`` — the ADR 0004 C6 violation) are
gone; the run history lives in scanning's ``ScanRun`` (read through the
published ``scan_gate_provider`` seam) and the findings live in the ONE SSOT
(read through the findings context's read seam). Keeps ORM out of the
controller (thin/ORM-free).

Honesty note vs the legacy card: severity counts are now OPEN SSOT findings
(deduped across scans, resolved/suppressed excluded) — the legacy card counted
every per-scan snapshot row ever written, inflating with each re-scan.
"""

from __future__ import annotations

_SOURCE = "cloud_posture.prowler"


def _severity_keys() -> dict:
    return {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}


def get_posture_summary(*, workspace_id) -> dict:
    """Per-account latest completed run + OPEN findings-by-severity, plus totals."""
    from django.db.models import Count

    from infrastructure.persistence.findings.models import Finding
    from infrastructure.persistence.scanning.models import ScanRun

    empty = _severity_keys()

    # Latest COMPLETED run per account (most recent created_at wins) — the same
    # "latest scan per account" contract the legacy snapshot table served.
    runs_by_account: dict[str, ScanRun] = {}
    runs = ScanRun.objects.filter(workspace_id=workspace_id, source=_SOURCE, status=ScanRun.Status.COMPLETED).order_by(
        "-created_at"
    )
    for run in runs:
        runs_by_account.setdefault(run.target_ref, run)

    # OPEN findings-by-severity per account (the AWS posture source only; the
    # account id rides each finding's attributes — value identity, no FK).
    per_account_sev: dict[str, dict] = {}
    sev_rows = (
        Finding.objects.filter(workspace_id=workspace_id, source=_SOURCE, status="open")
        .values("attributes__account_id", "severity")
        .annotate(n=Count("id"))
    )
    for row in sev_rows:
        account = str(row["attributes__account_id"] or "")
        per_account_sev.setdefault(account, dict(empty))
        per_account_sev[account][row["severity"]] = row["n"]

    accounts = []
    totals = dict(empty)
    for account_id, run in runs_by_account.items():
        sev = per_account_sev.get(account_id, dict(empty))
        for k, v in sev.items():
            totals[k] += v
        accounts.append(
            {
                "account_id": account_id,
                "connection_id": str(run.connection_id) if run.connection_id else "",
                "scan": {
                    "id": str(run.id),
                    "status": run.status,
                    "total_checks": run.total_checks,
                    "passed_count": run.passed_count,
                    "failed_count": run.failed_count,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                },
                "findings_by_severity": sev,
            }
        )

    return {
        "accounts": accounts,
        "account_count": len(accounts),
        "totals": {"findings_by_severity": totals},
    }


def list_findings(
    *, workspace_id, severity: str | None = None, account_id: str | None = None, limit: int = 100
) -> list[dict]:
    """Open findings for the drill-down — filter by severity and/or account.

    Newest first, capped at ``limit`` (the card shows a focused list, not a dump).
    Reads the Finding SSOT; the CSPM specifics ride each finding's attributes.
    """
    from infrastructure.persistence.findings.models import Finding

    qs = Finding.objects.filter(workspace_id=workspace_id, source=_SOURCE, status="open")
    if severity:
        qs = qs.filter(severity=severity)
    if account_id:
        qs = qs.filter(attributes__account_id=account_id)
    rows = qs.order_by("-last_seen_at")[: max(1, min(limit, 500))]
    return [
        {
            "id": str(f.id),
            "check_id": (f.attributes or {}).get("check_id", ""),
            "title": f.title,
            "severity": f.severity,
            "status": (f.attributes or {}).get("check_status", ""),
            "account_id": (f.attributes or {}).get("account_id", ""),
            "region": (f.attributes or {}).get("region", ""),
            "service": (f.attributes or {}).get("service", ""),
            "resource_name": (f.attributes or {}).get("resource_name", ""),
            "resource_uid": (f.attributes or {}).get("resource_uid", ""),
            "description": f.description,
            "remediation": f.remediation,
        }
        for f in rows
    ]


def is_workspace_member(*, user, workspace_id) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, status="active").exists()
