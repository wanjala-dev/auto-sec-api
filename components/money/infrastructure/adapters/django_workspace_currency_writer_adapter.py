"""Django adapter for WorkspaceCurrencyWriterPort.

Writes the ``default_currency`` cache on ``Workspace`` to track the connected
account's settlement currency. Single-column ``UPDATE`` guarded by an
``.exclude()`` so a no-op never issues a write. Mirrors the read-side adapter's
direct, single-column access.
"""

from __future__ import annotations

from ...application.ports.workspace_currency_writer_port import (
    WorkspaceCurrencyWriterPort,
)


class DjangoWorkspaceCurrencyWriterAdapter(WorkspaceCurrencyWriterPort):
    def write(self, *, workspace_id: str, currency: str) -> bool:
        from infrastructure.persistence.workspaces.models import Workspace

        normalized = (currency or "").strip().upper()
        if not workspace_id or not normalized:
            return False

        updated = (
            Workspace.objects.filter(pk=workspace_id)
            .exclude(default_currency=normalized)
            .update(default_currency=normalized)
        )
        return bool(updated)
