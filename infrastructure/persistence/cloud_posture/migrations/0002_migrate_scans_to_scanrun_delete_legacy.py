"""Retire the per-pillar CSPM snapshot tables (audit R2 / ADR 0004 C6).

1. DATA-MIGRATE every ``CloudPostureScan`` row into scanning's generic
   ``ScanRun`` (source ``cloud_posture.prowler``) so scan history survives the
   table drop — historical rows carry ``trigger="legacy"`` (pre-spine runs
   recorded no trigger/actor; inventing one would be dishonest).
2. DELETE ``CloudPostureFinding`` + ``CloudPostureScan``. The findings
   themselves are NOT lost: every actionable check has been dual-written into
   the Finding SSOT (``FindingObserved``) since the Phase 3b bridge — the SSOT
   row (deduped, lifecycle-tracked) is the canonical record; the per-scan
   snapshot granularity is superseded by ``ScanRun``'s counts.

Reverse: irreversible by design (the snapshot tables are the ADR 0004 C6
violation being retired) — the RunPython reverse is a no-op and the models'
recreation would come from re-applying 0001.
"""

from __future__ import annotations

from django.db import migrations

_SOURCE = "cloud_posture.prowler"


def copy_scans_to_scanruns(apps, schema_editor):
    CloudPostureScan = apps.get_model("cloud_posture", "CloudPostureScan")
    ScanRun = apps.get_model("scanning", "ScanRun")

    for scan in CloudPostureScan.objects.all().iterator(chunk_size=500):
        status = scan.status if scan.status in ("completed", "failed") else "completed"
        run = ScanRun.objects.create(
            workspace_id=scan.workspace_id,
            source=_SOURCE,
            target_ref=(scan.account_id or "")[:512],
            connection_id=scan.connection_id,
            account_id=(scan.account_id or "")[:32],
            trigger="legacy",
            triggered_by_id=None,
            status=status,
            engine="prowler",
            engine_version=scan.engine_version or "",
            total_checks=scan.total_checks,
            passed_count=scan.passed_count,
            failed_count=scan.failed_count,
            started_at=scan.started_at,
            completed_at=scan.completed_at,
        )
        # auto_now_add stamped "now" on insert; restore the honest history order.
        ScanRun.objects.filter(id=run.id).update(created_at=scan.created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("cloud_posture", "0001_initial"),
        ("scanning", "0002_scanrun_trigger_scanrun_triggered_by_id"),
    ]

    operations = [
        migrations.RunPython(copy_scans_to_scanruns, migrations.RunPython.noop),
        migrations.DeleteModel(name="CloudPostureFinding"),
        migrations.DeleteModel(name="CloudPostureScan"),
    ]
