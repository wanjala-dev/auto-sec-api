"""Provider/composition root for the workspace cache adapter.

The API controller (``components/workspace/api/controller.py``) consumes
:class:`WorkspaceCacheProvider` instead of importing
``DjangoCacheWorkspaceAdapter`` directly. This keeps the controller
import graph free of infrastructure dependencies — the architecture
test ``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter inside ``build_cache`` so this
module itself never pulls infra at import time. Tests can monkeypatch
``_default`` (or override ``WorkspaceCacheProvider.build_cache``) to
swap in a fake ``WorkspaceCachePort`` without touching Django.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from components.workspace.application.ports.workspace_cache_port import (
        WorkspaceCachePort,
    )


class WorkspaceCacheProvider:
    """Driving-side façade for the workspace cache adapter."""

    def build_cache(self) -> "WorkspaceCachePort":
        """Return a concrete ``WorkspaceCachePort`` implementation.

        Lazy-imports the Django-backed adapter so importing this
        provider module is cheap and free of infrastructure deps.
        """
        from components.workspace.infrastructure.adapters.django_cache_workspace_adapter import (
            DjangoCacheWorkspaceAdapter,
        )

        return DjangoCacheWorkspaceAdapter()


_default = WorkspaceCacheProvider()


def get_workspace_cache_provider() -> WorkspaceCacheProvider:
    """Return the default provider — composition root for the workspace
    cache adapter. Override by monkeypatching this module's ``_default``
    attribute in tests."""
    return _default
