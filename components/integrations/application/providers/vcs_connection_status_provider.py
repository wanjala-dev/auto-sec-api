"""Provider: composition root for the VCS credential-status read seam.

Wires :class:`VcsConnectionStatusReadPort` to its ORM adapter. Provider files are
the only place that decides which adapter implements the port (application-layer
policy — architecture-manifesto Rule 9); consumers (the AI-governance credential
inventory) depend on this function, never on the adapter module.

For the secret-containment contract this seam enforces,
see :mod:`components.integrations.infrastructure.adapters.vcs_connection_status_reader`.
"""

from __future__ import annotations

from components.integrations.application.ports.vcs_connection_status_port import (
    VcsConnectionStatusReadPort,
)


def get_vcs_connection_status_reader() -> VcsConnectionStatusReadPort:
    from components.integrations.infrastructure.adapters.vcs_connection_status_reader import (
        VcsConnectionStatusReader,
    )

    return VcsConnectionStatusReader()
