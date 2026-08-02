"""Repository for the per-(connection, channel) ingestion cursor.

The single ORM slot for ``IngestCheckpoint`` — the S3-list cursor that keeps the
error-scan idempotent (re-runs skip already-processed object keys). The ingest
service stays framework-free and drives the cursor through here (architecture
rule: the application layer never touches ``infrastructure.persistence``; ORM
lives in infrastructure repositories).
"""

from __future__ import annotations

from infrastructure.persistence.integrations.models import IngestCheckpoint


class IngestCheckpointRepository:
    """ORM access for the S3-list ingestion checkpoint, per connection."""

    def get_or_create_s3_list(self, connection) -> IngestCheckpoint:
        """The S3_LIST cursor for a connection's management account. Created on
        first scan; stateless SQS never needs this."""
        checkpoint, _ = IngestCheckpoint.objects.get_or_create(
            connection=connection,
            account_id=connection.management_account_id,
            region="",
            channel=IngestCheckpoint.Channel.S3_LIST,
        )
        return checkpoint

    def advance(
        self,
        checkpoint: IngestCheckpoint,
        *,
        last_object_key: str,
        objects_processed: int,
        events_processed: int,
    ) -> IngestCheckpoint:
        """Advance the cursor past the newest processed key and bump the counters
        so subsequent runs skip what this run consumed."""
        checkpoint.last_object_key = last_object_key
        checkpoint.objects_processed += objects_processed
        checkpoint.events_processed += events_processed
        checkpoint.save()
        return checkpoint
