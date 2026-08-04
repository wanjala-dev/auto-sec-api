"""Provider/composition root for the audit-log facade.

External controllers (campaign/event/sponsorship PATCH handlers)
should consume :class:`AuditLogProvider` instead of importing the
concrete facade in ``components.audit.infrastructure.services.audit_log``.
The test ``test_controllers_do_not_import_concrete_adapters`` enforces
this.

The provider only re-exports the **functions** the controllers actually
call today (``log_field_change`` and ``get_entity_history``). Each
method lazy-imports the infrastructure facade so this module has no
top-level cross-context infra imports and is safe to import from any
layer.
"""

from __future__ import annotations

from typing import Any


class AuditLogProvider:
    """Façade exposing the audit-log helper functions.

    Methods lazy-import the adapter so module load is cheap and the
    import graph never crosses the controller-→ infrastructure
    boundary.
    """

    def log_field_change(
        self,
        *,
        instance: Any,
        field_name: str,
        previous_value: Any,
        new_value: Any,
        actor: Any = None,
        reason: str = "",
    ) -> Any:
        """Record a field change for the given ORM instance.

        Delegates to the audit-log facade, which handles
        JSON-normalisation and no-op suppression. Returns the persisted
        ``AuditEntry`` or ``None`` when the edit is a no-op.
        """

        from components.audit.infrastructure.services.audit_log import (
            log_field_change as _log_field_change,
        )

        return _log_field_change(
            instance=instance,
            field_name=field_name,
            previous_value=previous_value,
            new_value=new_value,
            actor=actor,
            reason=reason,
        )

    def get_entity_history(
        self,
        *,
        instance: Any,
        field_name: str | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        """Return the audit history for the given ORM instance."""

        from components.audit.infrastructure.services.audit_log import (
            get_entity_history as _get_entity_history,
        )

        return _get_entity_history(
            instance=instance,
            field_name=field_name,
            limit=limit,
        )

    def entity_history_use_case(self) -> Any:
        """Return a wired ``GetEntityHistoryUseCase``.

        Composition root for the REST read path — the controller calls
        this instead of instantiating the repository itself.
        """

        from components.audit.application.providers.entity_audit_log_repository_provider import (
            get_entity_audit_log_repository_provider,
        )
        from components.audit.application.use_cases.get_entity_history_use_case import (
            GetEntityHistoryUseCase,
        )

        return GetEntityHistoryUseCase(
            audit_log=get_entity_audit_log_repository_provider().repository(),
        )

    def workspace_history_use_case(self) -> Any:
        """Return a wired ``GetWorkspaceHistoryUseCase``.

        Composition root for the auditor workspace-wide read path —
        same repository as the per-entity path, no entity narrowing
        required.
        """

        from components.audit.application.providers.entity_audit_log_repository_provider import (
            get_entity_audit_log_repository_provider,
        )
        from components.audit.application.use_cases.get_workspace_history_use_case import (
            GetWorkspaceHistoryUseCase,
        )

        return GetWorkspaceHistoryUseCase(
            audit_log=get_entity_audit_log_repository_provider().repository(),
        )


_default = AuditLogProvider()


def get_audit_log_provider() -> AuditLogProvider:
    """Return the default provider — composition root for the audit-log
    facade. Override by monkeypatching this module's ``_default``
    attribute in tests."""

    return _default
