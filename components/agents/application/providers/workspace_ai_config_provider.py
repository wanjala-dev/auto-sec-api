"""Provider/composition root for the workspace AI config adapter.

Controllers that need an ``WorkspaceAIConfigPort`` implementation (for
example ``components/identity/api/controller.py`` building the
messages-remaining quota snapshot on ``me/summary``) consume
:class:`WorkspaceAIConfigProvider` instead of instantiating the
concrete ``OrmWorkspaceAIConfigAdapter`` directly. Keeps the API
layer's import graph free of infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter so module load is cheap and
tests can monkeypatch ``provider.get_port`` to inject a fake port
without dragging in Django at test discovery time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from components.agents.application.ports.workspace_ai_config_port import (
        WorkspaceAIConfigPort,
    )


class WorkspaceAIConfigProvider:
    """Driving-side façade for the workspace AI config adapter."""

    def get_port(self) -> "WorkspaceAIConfigPort":
        """Return a concrete ``WorkspaceAIConfigPort`` instance.

        Lazy-imports the ORM adapter so the provider module has no
        top-level infra imports.
        """
        from components.agents.infrastructure.adapters.workspace_ai_config_adapter import (
            OrmWorkspaceAIConfigAdapter,
        )

        return OrmWorkspaceAIConfigAdapter()


_default = WorkspaceAIConfigProvider()


def get_workspace_ai_config_provider() -> WorkspaceAIConfigProvider:
    """Return the default provider — composition root for the workspace
    AI config adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
