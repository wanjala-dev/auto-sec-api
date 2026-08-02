"""Admin registration for RemediationEntry.

Read-only on purpose: the corpus is populated **only** by the entry-gate
(``RecordRemediationEntryUseCase``), never by hand — admin is for inspection, not
for asserting corpus membership (ADR 0012 D1). Revocation is a soft-delete.
"""

from __future__ import annotations

from django.contrib import admin

from infrastructure.persistence.remediation.models import RemediationEntry


@admin.register(RemediationEntry)
class RemediationEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "workspace", "finding_kind", "source_type", "approved_by", "resolved_at", "is_deleted")
    list_filter = ("finding_kind", "source_type", "is_deleted")
    search_fields = ("finding_task_id", "finding_fingerprint", "applied_pr_url")
    readonly_fields = tuple(f.name for f in RemediationEntry._meta.fields)

    # Read-only by design: creation is gate-only (D1) and mutation/deletion via
    # admin would bypass the gate + the soft-delete revocation semantics. Admin
    # is an inspection surface, never a write path into the corpus.
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
