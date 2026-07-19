import uuid
from django.db import models
from django.conf import settings


class RecycleBinEntry(models.Model):
    STAGE_TRASHED = "trashed"
    STAGE_TOMBSTONED = "tombstoned"
    STAGE_CHOICES = [
        (STAGE_TRASHED, "Trashed"),
        (STAGE_TOMBSTONED, "Tombstoned"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='recycle_bin_entries',
    )
    entity_type = models.CharField(max_length=64, db_index=True)
    # Stored as a string so the bin can hold any kind of PK — Transaction
    # and Budget use BigAutoField (int), but a future entity type might
    # legitimately use UUID. CharField with the entity_type+entity_id
    # uniqueness constraint already prevents collisions between
    # "transaction/6" and "budget/6".
    entity_id = models.CharField(max_length=64)
    entity_name = models.CharField(max_length=255)
    stage = models.CharField(max_length=16, choices=STAGE_CHOICES, default=STAGE_TRASHED)

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    deleted_at = models.DateTimeField()
    trashed_until = models.DateTimeField()

    tombstoned_at = models.DateTimeField(null=True, blank=True)
    tombstoned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    tombstoned_until = models.DateTimeField(null=True, blank=True)

    snapshot = models.JSONField(default=dict, blank=True)
    cascade_snapshot = models.JSONField(default=dict, blank=True)

    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        db_table = 'recycle_bin'
        indexes = [
            models.Index(fields=['workspace', 'stage', '-deleted_at'], name='rb_ws_stage_deleted_idx'),
            models.Index(fields=['entity_type', 'entity_id'], name='rb_entity_lookup_idx'),
            models.Index(fields=['stage', 'trashed_until'], name='rb_tombstone_cron_idx'),
            models.Index(fields=['stage', 'tombstoned_until'], name='rb_purge_cron_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['entity_type', 'entity_id'],
                name='rb_unique_entity',
            ),
        ]

    def __str__(self):
        return f"{self.stage}: {self.entity_type}/{self.entity_name}"
