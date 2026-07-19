"""Reusable guard callables for ai-app migrations.

Lives outside ``migrations/`` because migration filenames start with
digits (``0013_*``), which makes them un-importable by name. Pulling
the guard out into a regular module gives both the migration and the
test suite a single place to import from.

Belt-and-braces philosophy: the guard isn't there to replace the
``audit_orphan_documents`` command — it's there to fail loudly if
the audit was skipped or if a regression re-introduced orphans
between PR #343 shipping and the migration applying.
"""
from __future__ import annotations


def guard_no_orphan_documents(apps, schema_editor):
    """Refuse to add ``NOT NULL`` to Document.workspace if orphans remain.

    Counts ``workspace_id IS NULL`` rows and raises ``RuntimeError``
    with an actionable message naming the cleanup command. The
    alternative — letting Postgres reject the constraint add —
    surfaces a vague "violates not-null constraint" error that
    forces the operator to dig for the runbook.
    """
    Document = apps.get_model("ai", "Document")
    orphan_count = Document.objects.filter(workspace__isnull=True).count()
    if orphan_count:
        raise RuntimeError(
            f"Refusing to add NOT NULL constraint: {orphan_count} "
            "Document row(s) still have workspace_id=NULL. Run "
            "`python manage.py audit_orphan_documents --apply` "
            "to clean them up first."
        )


def guard_noop_reverse(apps, schema_editor):
    """No-op reverse for ``guard_no_orphan_documents``.

    The guard isn't a data change — a rollback doesn't need to
    undo anything. Defined explicitly so the migration is
    reversible (Django requires both directions or RunPython
    defaults to noreverse, which surprises operators trying to
    roll back the schema flip alone).
    """
    return
