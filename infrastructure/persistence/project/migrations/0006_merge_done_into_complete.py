"""Collapse the redundant "Done" team-board lane into "Complete" (F7).

User-created teams used to be seeded with a seventh "Done"(order 7) column on
top of the six canonical lanes ending in "Complete" — two synonymous terminal
lanes on the same board (QA report 2026-08-16, F7). The seeder no longer
creates "Done"; this data migration cleans up EXISTING boards:

- an EMPTY "Done" team-board column is removed;
- a "Done" with cards merges them into the board's "Complete" column,
  appending after Complete's existing cards and preserving the Done cards'
  relative order;
- a board with cards in "Done" but NO "Complete" column adopts the canonical
  name instead (rename Done -> Complete) so no card is ever orphaned;
- AI-agents team boards are never touched (their column vocabulary is owned
  by the agents context).

Idempotent: a re-run finds no project-less "Done" columns and no-ops.
"""

from django.db import migrations
from django.db.models import Max

# Kind value inlined (historical models expose no TextChoices helpers).
_AI_AGENTS_KIND = "ai_agents"


def merge_done_into_complete(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Column = apps.get_model("project", "Column")
    Task = apps.get_model("project", "Task")

    done_columns = (
        Column.objects.using(db_alias)
        .filter(project__isnull=True, title="Done", is_deleted=False)
        .select_related("team")
        .order_by("id")
    )
    for done in done_columns:
        if getattr(done.team, "kind", "") == _AI_AGENTS_KIND:
            continue  # never touch the AI board's columns

        done_tasks = Task.objects.using(db_alias).filter(column=done)
        if not done_tasks.exists():
            done.delete()
            continue

        complete = (
            Column.objects.using(db_alias)
            .filter(
                project__isnull=True,
                team=done.team,
                workspace=done.workspace,
                title="Complete",
            )
            .order_by("id")
            .first()
        )
        if complete is None:
            # No Complete lane to merge into — adopt the canonical name so the
            # cards stay exactly where the operator can see them.
            done.title = "Complete"
            done.save(update_fields=["title"])
            continue

        if complete.is_deleted:
            # The canonical lane was soft-deleted but Done holds live cards —
            # restore Complete rather than merging cards into a hidden lane
            # (the partial-unique constraint also forbids renaming Done while
            # this row exists).
            complete.is_deleted = False
            complete.save(update_fields=["is_deleted"])

        base_order = (
            Task.objects.using(db_alias).filter(column=complete).aggregate(max_order=Max("order"))["max_order"] or 0
        )
        for offset, task in enumerate(done_tasks.order_by("order", "created_at"), start=1):
            task.column = complete
            task.order = base_order + offset
            task.save(update_fields=["column", "order"])

        done.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("project", "0005_alter_column_options"),
        # Column.team -> Team; the merge reads ``team.kind`` from migration state.
        ("team", "0005_seed_red_blue_teams"),
    ]

    operations = [
        # Irreversible by design: the merge destroys which lane a card came
        # from. Reverse is a no-op so the migration can still be unwound.
        migrations.RunPython(merge_done_into_complete, migrations.RunPython.noop),
    ]
