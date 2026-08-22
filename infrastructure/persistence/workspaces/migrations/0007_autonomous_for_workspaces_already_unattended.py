"""Make the dial tell the truth about workspaces that ALREADY run unattended.

ADR 0035 D2 gives AUTONOMOUS a job: it decides whether the scheduler starts runs
on its own. Before that gate existed, eligibility came from
``ai_teammate_enabled`` alone — so a workspace could be receiving unattended
teammate cycles every five minutes while its dial displayed ASSIST.

The dial was wrong about them, not the other way round. This sets
``autonomy_mode = 'autonomous'`` for exactly the workspaces the scheduler was
already picking up, which:

- **changes no behaviour.** The set of workspaces receiving unattended runs
  after the new filter is identical to the set before it. D2's "default stays
  ASSIST so nobody's behaviour changes on deploy" is preserved — for these rows
  ASSIST was never what was actually happening.
- **corrects a misleading display** rather than granting anything. Per D3
  AUTONOMOUS confers no extra permission; irreversible actions still require
  approval. The only thing it now states is who starts the run, which for these
  workspaces was already the scheduler.

Deliberately NOT touched: workspaces with the kill switch off. They receive no
unattended runs today, so ASSIST is accurate for them and moving them would be
the silent widening this migration exists to avoid.

Reversible: the backward step returns them to ASSIST, which is what the column
said before — losing only the correction, never real data.
"""

from django.db import migrations


def mark_already_unattended_as_autonomous(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Workspace.objects.filter(ai_teammate_enabled=True, autonomy_mode="assist").update(autonomy_mode="autonomous")


def back_to_assist(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Workspace.objects.filter(ai_teammate_enabled=True, autonomy_mode="autonomous").update(autonomy_mode="assist")


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0006_workspace_autonomy_mode"),
    ]

    operations = [
        migrations.RunPython(mark_already_unattended_as_autonomous, back_to_assist),
    ]
