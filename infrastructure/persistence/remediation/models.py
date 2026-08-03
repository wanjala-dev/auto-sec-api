"""ORM for the Remediation Memory corpus (ADR 0012 Phase 3).

One row per **accepted + applied + resolved** fix — the vetted, per-workspace
knowledge base the triage agent will later retrieve from. This is *storage only*;
the entry-gate that decides whether a row may exist at all lives in the
``remediation`` bounded context (``RecordRemediationEntryUseCase``) — the model
carries no write logic and MUST NOT be created outside that gate.

Security-critical invariants this table exists to serve (ADR 0012 D1/D3/D4):

- **D1 — gated membership.** A row is proof that all three conditions held
  (sign-off approved, draft PR applied, finding resolved). The gate is the sole
  creator; there is no admin/controller create path. Corpus membership is
  *earned*, never *asserted* — this structurally denies RAG poisoning.
- **D3 — raw, not rendered.** ``code`` stores RAW fix text + ``language`` only.
  We never store rendered/highlighted HTML (that would be a stored-XSS vector);
  highlighting + sanitisation happen at render time.
- **D4 — per-workspace isolation.** Every retrieval filters ``workspace_id``.
  The corpus never crosses a tenant boundary; the ``.active`` manager and every
  repository read are workspace-scoped.

Soft-delete (``is_deleted`` + the ``.active`` manager) backs the P5 *revocation*
path — when a vetted fix's finding reopens, the entry is pulled from the
retrievable corpus without losing the audit row.
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ActiveRemediationEntryManager(models.Manager):
    """Only non-revoked entries — the retrievable corpus. Retrieval and every
    tenant-scoped read go through this, never ``objects.filter(is_deleted=...)``.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class RemediationEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Relations — the tenant boundary (D4). Every query filters on this.
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="remediation_entries")
    # Retrieval keys — WHAT class of finding this fix is for (the later RAG key).
    finding_kind = models.CharField(max_length=64, db_index=True)
    source_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    tags = models.JSONField(default=list, blank=True)
    # The fix itself — RAW code + language only (D3: never rendered HTML).
    language = models.CharField(max_length=48, blank=True, default="")
    code = models.TextField()
    title = models.CharField(max_length=255, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    # Provenance link — the board fact and the library entry are the SAME fact
    # (ADR 0012). We LINK to the finding/task + the provenance event, never copy.
    finding_task_id = models.CharField(max_length=64, db_index=True)
    finding_fingerprint = models.CharField(max_length=255, blank=True, default="", db_index=True)
    provenance_event_ref = models.CharField(max_length=255, blank=True, default="")
    # The three gate facts, recorded as evidence the gate passed (D1).
    applied_pr_url = models.URLField(max_length=1024)
    approved_by = models.CharField(max_length=64)
    resolved_at = models.DateTimeField()
    # Outcome / ranking (ADR 0012 P5 — the "did this fix hold?" loop).
    #
    # ``score`` is DERIVED from the outcome counters below by
    # ``RemediationRankingPolicy.derive_score`` — never set from raw user input, so
    # a caller cannot forge a ranking (D-poisoning residual: rating can't be gamed).
    # Retrieval blends this rating with vector similarity so proven fixes outrank
    # unproven ones. The counters:
    #   reuse_count      — times this entry grounded a later same-class fix that landed
    #   success_count    — of those reuses, how many merged/resolved (a "held" signal)
    #   recurrence_count — times the finding this fix closed came back (a "didn't hold" signal)
    reuse_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    recurrence_count = models.PositiveIntegerField(default=0)
    last_outcome_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(default=0, db_index=True)
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    objects = models.Manager()
    active = ActiveRemediationEntryManager()

    class Meta:
        indexes = [
            # per-workspace retrieval by finding class, newest-first (D4 filter).
            models.Index(fields=["workspace", "finding_kind", "-created_at"]),
            models.Index(fields=["workspace", "is_deleted", "-created_at"]),
            # idempotency / one-entry-per-fix lookups keyed on the source finding.
            models.Index(fields=["workspace", "finding_task_id"]),
        ]
        constraints = [
            # STRUCTURAL idempotency (ADR 0012 "one entry per fix"): the DB — not a
            # check-then-save window — is the source of truth. At most ONE ACTIVE
            # (non-revoked) entry per (workspace, finding_task_id). A concurrent
            # second insert violates this and is caught as an idempotent no-op in
            # the repository. Partial (condition=is_deleted=False) so revocation +
            # re-capture of the same finding stays possible: a soft-deleted row does
            # not block a fresh active one.
            models.UniqueConstraint(
                fields=["workspace", "finding_task_id"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_remediation_per_finding",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"RemediationEntry[{self.finding_kind}] ws={self.workspace_id} task={self.finding_task_id}"
