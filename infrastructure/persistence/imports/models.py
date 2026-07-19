"""Shared document import models.

Generic import pipeline for any entity type — expenses, income, budgets,
recipients, donations, events, campaigns, etc.  The ``import_type`` field
determines which extraction prompt and applier are used.

Lifecycle:
    pending → queued → parsing → ready | needs_review | failed → applied
"""
from django.conf import settings
from django.db import models

from infrastructure.persistence.uploads.models import File


class DocumentImport(models.Model):
    """A single import job — one uploaded file being processed."""

    # ── Status machine ───────────────────────────────────────────
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_PARSING = "parsing"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_READY = "ready"
    STATUS_APPLIED = "applied"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_PARSING, "Parsing"),
        (STATUS_NEEDS_REVIEW, "Needs Review"),
        (STATUS_READY, "Ready"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_FAILED, "Failed"),
    ]

    # ── Import type — what kind of records are we extracting? ────
    TYPE_EXPENSE = "expense"
    TYPE_INCOME = "income"
    TYPE_BUDGET = "budget"
    TYPE_RECIPIENT = "recipient"
    TYPE_DONATION = "donation"
    TYPE_EVENT = "event"
    TYPE_CAMPAIGN = "campaign"
    TYPE_PROJECT = "project"
    TYPE_CONTACT = "contact"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_EXPENSE, "Expenses"),
        (TYPE_INCOME, "Income"),
        (TYPE_BUDGET, "Budget"),
        (TYPE_RECIPIENT, "Recipients"),
        (TYPE_DONATION, "Donations"),
        (TYPE_EVENT, "Events"),
        (TYPE_CAMPAIGN, "Campaigns"),
        (TYPE_PROJECT, "Projects"),
        (TYPE_CONTACT, "Contacts"),
        (TYPE_OTHER, "Other"),
    ]

    # ── Source format ────────────────────────────────────────────
    FORMAT_CSV = "csv"
    FORMAT_PDF = "pdf"
    FORMAT_DOCX = "docx"
    FORMAT_DOC = "doc"
    FORMAT_XLSX = "xlsx"
    FORMAT_XLS = "xls"
    FORMAT_JSON = "json"
    FORMAT_TXT = "txt"
    FORMAT_UNKNOWN = "unknown"
    FORMAT_CHOICES = [
        (FORMAT_CSV, "CSV"),
        (FORMAT_PDF, "PDF"),
        (FORMAT_DOCX, "Word (DOCX)"),
        (FORMAT_DOC, "Word (DOC)"),
        (FORMAT_XLSX, "Excel (XLSX)"),
        (FORMAT_XLS, "Excel (XLS)"),
        (FORMAT_JSON, "JSON"),
        (FORMAT_TXT, "Text"),
        (FORMAT_UNKNOWN, "Unknown"),
    ]

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="document_imports",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_imports",
    )
    source_file = models.ForeignKey(
        File,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_imports",
    )
    original_filename = models.CharField(max_length=512, blank=True)
    import_type = models.CharField(
        max_length=32,
        choices=TYPE_CHOICES,
        default=TYPE_EXPENSE,
        db_index=True,
    )
    source_format = models.CharField(
        max_length=32,
        choices=FORMAT_CHOICES,
        default=FORMAT_UNKNOWN,
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    # ── Counts ───────────────────────────────────────────────────
    row_count = models.PositiveIntegerField(default=0)
    valid_row_count = models.PositiveIntegerField(default=0)
    applied_row_count = models.PositiveIntegerField(default=0)

    # ── Flexible metadata ────────────────────────────────────────
    summary = models.JSONField(default=dict, blank=True)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Import-type-specific config (e.g. budget_id, target entity).",
    )
    use_ai = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    # ── Timestamps ───────────────────────────────────────────────
    queued_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # ── Resilience: heartbeat + retry counter so a watchdog can
    # recover from silent worker deaths (OOM, container restart,
    # OpenAI hanging). ``last_heartbeat_at`` is stamped periodically
    # inside the parse task; the sweeper uses it to distinguish a
    # truly-stuck job from a slow-but-alive one.
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["workspace", "status"],
                name="docimport_ws_status",
            ),
            models.Index(
                fields=["workspace", "import_type"],
                name="docimport_ws_type",
            ),
            models.Index(
                fields=["status", "created_at"],
                name="docimport_status_created",
            ),
        ]

    def __str__(self):
        label = self.original_filename or f"Import {self.pk}"
        return f"{label} ({self.get_status_display()})"


class DocumentImportRow(models.Model):
    """A single parsed row from a document import.

    The ``parsed_data`` JSONField holds type-specific fields so the
    same model works for expenses, recipients, budgets, etc.
    """

    ROW_STATUS_PENDING = "pending"
    ROW_STATUS_APPROVED = "approved"
    ROW_STATUS_APPLIED = "applied"
    ROW_STATUS_SKIPPED = "skipped"
    ROW_STATUS_CHOICES = [
        (ROW_STATUS_PENDING, "Pending"),
        (ROW_STATUS_APPROVED, "Approved"),
        (ROW_STATUS_APPLIED, "Applied"),
        (ROW_STATUS_SKIPPED, "Skipped"),
    ]

    document_import = models.ForeignKey(
        DocumentImport,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_index = models.PositiveIntegerField(default=0, db_index=True)
    label = models.CharField(max_length=512, blank=True)
    amount = models.DecimalField(
        max_digits=13, decimal_places=2, null=True, blank=True
    )
    date = models.DateField(null=True, blank=True)
    category_name = models.CharField(max_length=255, blank=True)
    row_type = models.CharField(max_length=32, blank=True, default="expense")
    notes = models.TextField(blank=True)

    # ── Flexible structured data ─────────────────────────────────
    parsed_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full parsed data from LLM/parser. Schema varies by import_type.",
    )
    raw_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Original raw data before parsing/normalisation.",
    )

    # ── Validation ───────────────────────────────────────────────
    is_valid = models.BooleanField(default=True)
    validation_errors = models.JSONField(default=list, blank=True)
    user_modified = models.BooleanField(default=False)
    status = models.CharField(
        max_length=32,
        choices=ROW_STATUS_CHOICES,
        default=ROW_STATUS_PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["row_index", "created_at"]
        indexes = [
            models.Index(
                fields=["document_import", "row_index"],
                name="docimport_row_idx",
            ),
            models.Index(
                fields=["document_import", "status"],
                name="docimport_row_status",
            ),
        ]

    def __str__(self):
        label = self.label or self.category_name or f"Row {self.row_index}"
        return f"{label} (import {self.document_import_id})"
