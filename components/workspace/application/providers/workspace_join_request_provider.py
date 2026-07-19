"""Provider/composition root for the workspace join-request repository.

The API controller (``components/workspace/api/controller.py``) consumes
:class:`WorkspaceJoinRequestProvider` instead of importing
``OrmWorkspaceJoinRequestRepository`` directly. This keeps the
controller import graph free of infrastructure dependencies — the
architecture test ``test_controllers_do_not_import_concrete_adapters``
enforces this.

The provider lazy-imports the ORM adapter inside ``build_store`` so
this module itself never pulls infra at import time. Tests can
monkeypatch ``_default`` to swap in a fake
``WorkspaceJoinRequestPort`` without touching the ORM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from components.workspace.application.ports.workspace_join_request_port import (
        WorkspaceJoinRequestPort,
    )


class WorkspaceJoinRequestProvider:
    """Driving-side façade for the workspace join-request repository."""

    def build_store(self) -> "WorkspaceJoinRequestPort":
        """Return a concrete ``WorkspaceJoinRequestPort`` implementation.

        Lazy-imports the ORM-backed repository so importing this
        provider module is cheap and free of infrastructure deps.
        """
        from components.workspace.infrastructure.repositories.workspace_join_request_repository import (
            OrmWorkspaceJoinRequestRepository,
        )

        return OrmWorkspaceJoinRequestRepository()


_default = WorkspaceJoinRequestProvider()


def get_workspace_join_request_provider() -> WorkspaceJoinRequestProvider:
    """Return the default provider — composition root for the
    workspace join-request repository. Override by monkeypatching
    this module's ``_default`` attribute in tests."""
    return _default
