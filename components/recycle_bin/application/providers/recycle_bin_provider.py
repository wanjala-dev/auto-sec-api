"""Composition root for the recycle bin bounded context.

Wires ports to concrete adapters. This is a policy decision owned by
the application layer — infrastructure never decides which adapter to use.
"""

from __future__ import annotations

from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.application.service import RecycleBinService
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy

_service: RecycleBinService | None = None


def get_recycle_bin_service() -> RecycleBinService:
    """Return a lazily-initialized RecycleBinService singleton."""
    global _service
    if _service is not None:
        return _service

    from components.audit.application.providers.entity_audit_log_repository_provider import (
        get_entity_audit_log_repository_provider,
    )

    EntityAuditLogRepository = lambda: get_entity_audit_log_repository_provider().repository()  # noqa: E731
    # Wire the soft delete adapters for each trashable entity type. The
    # budgeting, sponsorship, templates, and content contexts were removed from
    # this fork, so their soft-delete providers are no longer registered.
    from components.identity.application.providers.login_activity_soft_delete_provider import (
        get_login_activity_soft_delete_provider,
    )
    from components.project.application.providers.project_soft_delete_provider import (
        get_project_soft_delete_provider,
    )
    from components.recycle_bin.infrastructure.adapters.entity_audit_log_adapter import (
        EntityAuditLogAuditAdapter,
    )
    from components.recycle_bin.infrastructure.repositories.recycle_bin_repository import DjangoRecycleBinRepository
    from components.workflow.application.providers.workflow_soft_delete_provider import (
        get_workflow_soft_delete_provider,
    )
    from components.workspace.application.providers.brand_asset_provider import (
        get_brand_asset_provider,
    )

    provider = SoftDeleteProvider()
    # Org login-activity hides (T2-S4): the trashable entity is the
    # per-workspace exclusion row, never the audit event itself.
    provider.register(get_login_activity_soft_delete_provider().adapter())
    provider.register(get_workflow_soft_delete_provider().adapter())
    provider.register(get_project_soft_delete_provider().adapter())
    provider.register(get_project_soft_delete_provider().task_adapter())
    provider.register(get_project_soft_delete_provider().column_adapter())
    provider.register(get_brand_asset_provider().soft_delete_adapter())

    # Production audit adapter writes every trash/restore/purge into
    # the shared EntityAuditLog table, so the existing
    # /audit/entries/?entity_type=…&object_id=… read endpoint surfaces
    # them alongside field-level edits. NullAuditLogAdapter is kept
    # around for tests + management commands that don't need DB-backed
    # audit.
    audit_log = EntityAuditLogAuditAdapter(
        shared_audit_log=EntityAuditLogRepository(),
    )

    _service = RecycleBinService(
        store=DjangoRecycleBinRepository(),
        provider=provider,
        audit_log=audit_log,
        policy=RetentionPolicy(),
    )
    return _service
