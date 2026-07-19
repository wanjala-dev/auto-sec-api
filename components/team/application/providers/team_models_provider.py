"""Provider for team ORM model lookups.

Controllers (and other application-layer call sites) should never
import ``infrastructure.persistence.team.models`` directly. Instead,
they obtain a :class:`TeamModelsProvider` via
:func:`get_team_models_provider` and access models as attributes.

The provider lazy-imports each model class inside the property body so
that this module remains framework-free at import time — only stdlib
and :mod:`typing` are referenced at module top.

Typical usage in a controller::

    from components.team.application.providers.team_models_provider import (
        get_team_models_provider,
    )

    Team = get_team_models_provider().Team
    Team.objects.filter(workspace_id=workspace_id)

This mirrors the existing dynamic-provider pattern used by other
bounded contexts (see ``magic_link_provider``,
``bank_overview_repository_provider``, ``retrieval_chain_provider``).
"""

from __future__ import annotations

from typing import Any


class TeamModelsProvider:
    """Façade over ``infrastructure.persistence.team.models``.

    Each ORM model is exposed as a ``@property`` that lazy-imports the
    concrete class on first access. This keeps the controller call
    sites untouched (``Model.objects.filter(...)`` still works) while
    routing every read through a single, swappable seam.
    """

    @property
    def Team(self) -> Any:
        from infrastructure.persistence.team.models import Team

        return Team

    @property
    def Invitation(self) -> Any:
        from infrastructure.persistence.team.models import Invitation

        return Invitation

    @property
    def TeamMembership(self) -> Any:
        from infrastructure.persistence.team.models import TeamMembership

        return TeamMembership

    @property
    def WorkspaceMembership(self) -> Any:
        # Preserves the existing controller import path even though the
        # canonical home for this model is the workspaces persistence
        # package. The lookup matches what the controller currently does
        # via ``from infrastructure.persistence.team.models import
        # WorkspaceMembership``.
        from infrastructure.persistence.team.models import WorkspaceMembership

        return WorkspaceMembership


_default = TeamModelsProvider()


def get_team_models_provider() -> TeamModelsProvider:
    """Return the process-wide default :class:`TeamModelsProvider`."""

    return _default
