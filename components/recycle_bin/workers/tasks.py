from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(name="recycle_bin.tombstone_expired_trash")
def tombstone_expired_trash():
    """Move expired TRASHED entries to TOMBSTONED stage (hard-deletes originals)."""
    from datetime import datetime, timezone

    from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
    from components.recycle_bin.application.use_cases.purge_expired_use_case import PurgeExpiredUseCase
    from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy
    from components.recycle_bin.infrastructure.adapters.null_audit_log_adapter import NullAuditLogAdapter
    from components.recycle_bin.infrastructure.repositories.recycle_bin_repository import DjangoRecycleBinRepository

    use_case = PurgeExpiredUseCase(
        store=DjangoRecycleBinRepository(),
        provider=SoftDeleteProvider(),
        audit_log=NullAuditLogAdapter(),
        policy=RetentionPolicy(),
    )
    count = use_case.tombstone_expired_trash(datetime.now(timezone.utc))
    logger.info("recycle_bin: tombstoned %d expired trash entries", count)


@shared_task(name="recycle_bin.purge_expired_tombstones")
def purge_expired_tombstones():
    """Permanently delete expired TOMBSTONED bin entries."""
    from datetime import datetime, timezone

    from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
    from components.recycle_bin.application.use_cases.purge_expired_use_case import PurgeExpiredUseCase
    from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy
    from components.recycle_bin.infrastructure.adapters.null_audit_log_adapter import NullAuditLogAdapter
    from components.recycle_bin.infrastructure.repositories.recycle_bin_repository import DjangoRecycleBinRepository

    use_case = PurgeExpiredUseCase(
        store=DjangoRecycleBinRepository(),
        provider=SoftDeleteProvider(),
        audit_log=NullAuditLogAdapter(),
        policy=RetentionPolicy(),
    )
    count = use_case.purge_expired_tombstones(datetime.now(timezone.utc))
    logger.info("recycle_bin: purged %d expired tombstone entries", count)
