"""
AI Models for document and chunk persistence
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

try:
    from infrastructure.persistence.workspaces.models import Workspace
except ImportError:  # pragma: no cover - fallback for migrations
    Workspace = None


class TimestampedModel(models.Model):
    """Abstract helper for created/updated fields."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

User = get_user_model()


class Document(TimestampedModel):
    """Model for storing documents for retrieval.

    ``workspace`` is **required** at the schema level. Tier 2 #4
    (PR #280) added the FK as nullable so pre-existing un-scoped rows
    didn't block the migration; the ``audit_orphan_documents``
    management command (PR #343) cleaned the remaining orphans by
    backfilling from ``metadata.workspace_id`` where recoverable and
    deleting the rest. The non-nullable flip in migration 0013 closes
    Tier 2 #4a — the upload endpoint already required workspace_id
    for every new row, so the schema constraint now matches the
    application contract.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    source = models.CharField(max_length=255, blank=True)  # URL, file path, etc.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'ai_documents'
        indexes = [
            models.Index(fields=['-created_at'], name='ai_document_created_idx'),
            models.Index(fields=['source'], name='ai_document_source_idx'),
            models.Index(
                fields=['workspace', '-created_at'],
                name='ai_doc_ws_created_idx',
            ),
        ]

    def __str__(self):
        return self.title


class DocumentChunk(models.Model):
    """Model for storing document chunks for vector search"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='chunks'
    )
    content = models.TextField()
    chunk_index = models.IntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['document', 'chunk_index']
        db_table = 'ai_document_chunks'
        unique_together = ['document', 'chunk_index']
        indexes = [
            models.Index(fields=['document', 'chunk_index'], name='ai_chunk_doc_idx'),
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"


class EmbeddingChunk(models.Model):
    """Stores document chunks with pgvector embeddings for semantic search.

    This table is the pgvector alternative to Elasticsearch dense_vector
    storage.  The ``embedding`` column uses raw SQL (the pgvector ``vector``
    type is not natively supported by the Django ORM, so the column is
    created via a RunSQL migration).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_embedding_chunks'
        indexes = [
            models.Index(fields=['-created_at'], name='ai_emb_chunk_created_idx'),
        ]

    def __str__(self):
        pdf_id = (self.metadata or {}).get('pdf_id', 'unknown')
        return f"EmbeddingChunk {self.pk} (pdf={pdf_id})"


class AITeammateProfile(TimestampedModel):
    """Per-workspace automation account configuration."""

    STATUS_ACTIVE = 'active'
    STATUS_PAUSED = 'paused'
    STATUS_DISABLED = 'disabled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAUSED, 'Paused'),
        (STATUS_DISABLED, 'Disabled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,
        related_name='ai_teammate_profile',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='ai_teammate_profiles',
    )
    display_name = models.CharField(max_length=80, blank=True, null=True)
    # The assistant's avatar shown wherever the teammate speaks (chat
    # window, message rows). Sits beside ``display_name`` because the
    # teammate profile IS the assistant's identity record — brand voice
    # (how the ORG sounds) stays on the brand kit, not here. Blank means
    # the platform default (the Octopus mark).
    avatar_url = models.CharField(max_length=1000, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'ai_teammate_profiles'
        indexes = [
            models.Index(fields=['status'], name='ai_teammate_status_idx'),
            models.Index(fields=['user'], name='ai_teammate_user_idx'),
        ]

    def __str__(self):
        workspace_ref = getattr(self.workspace, 'workspace_name', None) or str(getattr(self.workspace, 'id', 'unknown'))
        return f"Orchestrator Agent for {workspace_ref}"


class AIPermissionGrant(TimestampedModel):
    """Role grant for an AI principal within a workspace."""

    ROLE_AI_EXECUTOR = 'ai_executor'
    ROLE_CHOICES = [
        (ROLE_AI_EXECUTOR, 'AI Executor'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_DISABLED = 'disabled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_DISABLED, 'Disabled'),
    ]

    SCOPE_WORKSPACE = 'workspace'
    SCOPE_DEPARTMENT = 'department'
    SCOPE_PROJECT = 'project'
    SCOPE_CHOICES = [
        (SCOPE_WORKSPACE, 'Workspace'),
        (SCOPE_DEPARTMENT, 'Department'),
        (SCOPE_PROJECT, 'Project'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='ai_permission_grants')
    principal = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_permission_grants')
    role = models.CharField(max_length=64, choices=ROLE_CHOICES, default=ROLE_AI_EXECUTOR)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    scope_type = models.CharField(max_length=32, choices=SCOPE_CHOICES, default=SCOPE_WORKSPACE)
    scope_id = models.CharField(max_length=64, null=True, blank=True)
    actions = models.JSONField(default=list, blank=True)
    scopes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'ai_permission_grants'
        unique_together = [('workspace', 'principal', 'role', 'scope_type', 'scope_id')]
        indexes = [
            models.Index(fields=['workspace', 'role', 'status'], name='ai_perm_ws_role_status_idx'),
            models.Index(fields=['principal', 'status'], name='ai_perm_principal_status_idx'),
            models.Index(fields=['scope_type', 'scope_id'], name='ai_perm_scope_idx'),
        ]

    def __str__(self):
        return f"{self.role} :: {self.workspace_id} :: {self.principal_id} ({self.status})"


