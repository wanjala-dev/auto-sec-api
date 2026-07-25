"""Read model for the HUD CLOUD POSTURE card.

Aggregates the latest CSPM scan + open findings-by-severity per connected
account for a workspace. Keeps ORM out of the controller (thin/ORM-free).
"""

from __future__ import annotations


def get_posture_summary(*, workspace_id) -> dict:
    """Per-account latest scan + findings-by-severity, plus workspace totals."""
    from django.db.models import Count

    from infrastructure.persistence.cloud_posture.models import (
        CloudPostureFinding,
        CloudPostureScan,
        Severity,
    )

    empty = {s.value: 0 for s in Severity}

    # Latest scan per account (most recent created_at wins).
    scans_by_account: dict[str, CloudPostureScan] = {}
    for scan in CloudPostureScan.objects.filter(workspace_id=workspace_id).order_by("-created_at"):
        scans_by_account.setdefault(scan.account_id, scan)

    # Findings-by-severity per account (across that account's findings).
    per_account_sev: dict[str, dict] = {}
    for row in (
        CloudPostureFinding.objects.filter(workspace_id=workspace_id)
        .values("account_id", "severity")
        .annotate(n=Count("id"))
    ):
        per_account_sev.setdefault(row["account_id"], dict(empty))[row["severity"]] = row["n"]

    accounts = []
    totals = dict(empty)
    for account_id, scan in scans_by_account.items():
        sev = per_account_sev.get(account_id, dict(empty))
        for k, v in sev.items():
            totals[k] += v
        accounts.append(
            {
                "account_id": account_id,
                "connection_id": str(scan.connection_id) if scan.connection_id else "",
                "scan": {
                    "id": str(scan.id),
                    "status": scan.status,
                    "total_checks": scan.total_checks,
                    "passed_count": scan.passed_count,
                    "failed_count": scan.failed_count,
                    "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                },
                "findings_by_severity": sev,
            }
        )

    return {
        "accounts": accounts,
        "account_count": len(accounts),
        "totals": {"findings_by_severity": totals},
    }


def is_workspace_member(*, user, workspace_id) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, status="active").exists()
