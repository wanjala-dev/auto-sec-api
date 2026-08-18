"""Re-point the AI-findings-accepted workflow filter onto the canonical lane.

ADR 0030 P3 (D2) retires the AI board's "Accepted" column — a human accepting
an AI finding now moves the card into the canonical **Complete** lane. The
``ai-findings-accepted`` system template (and every per-workspace ``Workflow``
cloned from it) matches on ``publish_event``'s ``new_column_title`` filter,
which would otherwise watch a lane that no longer receives cards — silently
killing the ``TaskAcceptedFromBoard`` fan-out for every existing workspace.

Rewrites ``new_column_title: "Accepted" -> "Complete"`` in:

- the ``ai-findings-accepted`` ``WorkflowTemplate.default_graph``;
- every ``Workflow.graph`` cloned from that template (the engine executes
  ``run.workflow.graph``, so live clones are the load-bearing rows).

``WorkflowVersion`` snapshots are immutable history and deliberately left
untouched. Re-runnable (a graph already on "Complete" is skipped); reverse
restores "Accepted" for the P3 rollback (reversing project migration 0009
brings the Accepted column back).
"""

from django.db import migrations

TEMPLATE_ID = "ai-findings-accepted"


def _rewrite_graph(graph, old_title, new_title):
    """Return (changed, graph) with publish_event new_column_title rewritten."""
    changed = False
    for node in (graph or {}).get("nodes", []):
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        filters = config.get("filters")
        if not isinstance(filters, dict):
            continue
        if (filters.get("new_column_title") or "").strip().lower() == old_title.lower():
            filters["new_column_title"] = new_title
            changed = True
    return changed, graph


def _repoint(apps, schema_editor, *, old_title, new_title):
    db_alias = schema_editor.connection.alias
    WorkflowTemplate = apps.get_model("workflows", "WorkflowTemplate")
    Workflow = apps.get_model("workflows", "Workflow")

    template = WorkflowTemplate.objects.using(db_alias).filter(id=TEMPLATE_ID).first()
    if template is not None:
        changed, graph = _rewrite_graph(template.default_graph, old_title, new_title)
        if changed:
            template.default_graph = graph
            template.save(update_fields=["default_graph"])

    clones = Workflow.objects.using(db_alias).filter(template_id=TEMPLATE_ID).iterator(chunk_size=200)
    for workflow in clones:
        changed, graph = _rewrite_graph(workflow.graph, old_title, new_title)
        if changed:
            workflow.graph = graph
            workflow.save(update_fields=["graph"])


def forwards(apps, schema_editor):
    _repoint(apps, schema_editor, old_title="Accepted", new_title="Complete")


def backwards(apps, schema_editor):
    _repoint(apps, schema_editor, old_title="Complete", new_title="Accepted")


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0003_alter_workflowenrollment_target_type_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
