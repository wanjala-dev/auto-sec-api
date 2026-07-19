"""Provider/composition root for the workspace-write-access ``Q`` helper.

Controllers MUST consume :class:`WorkspaceAccessQueryProvider` instead of
importing
``components.shared_platform.infrastructure.services.workspace_access``
directly. The arch test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

Note: this is the **Q-builder** facade used by repository querysets. It is
distinct from ``workspace_access_provider.py`` which returns the search
``WorkspaceAccessPort`` adapter. Keep both — they serve different
adapters.
"""

from __future__ import annotations

from typing import Any


class WorkspaceAccessQueryProvider:
    """Driving-side façade for the workspace-writer ``Q`` helper."""

    def workspace_writer_q(self, *args: Any, **kwargs: Any) -> Any:
        from components.shared_platform.infrastructure.services.workspace_access import (
            workspace_writer_q as _workspace_writer_q,
        )

        return _workspace_writer_q(*args, **kwargs)


_default = WorkspaceAccessQueryProvider()


def get_workspace_access_query_provider() -> WorkspaceAccessQueryProvider:
    """Return the default provider — composition root for the workspace-write
    ``Q`` helper.

    Override by monkeypatching this module's ``_default`` attribute in tests.
    """
    return _default
