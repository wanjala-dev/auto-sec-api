"""Model provider for ``infrastructure.persistence.workspaces`` ORM classes.

Controllers must not import Django ORM models directly — the
Explicit Architecture rules forbid the API layer from depending on
concrete persistence implementations. Each controller obtains a model
class via this provider's lazy lookup.

The class methods perform the ``from infrastructure.persistence...``
import inside the property body so module import time stays
framework-free (stdlib + ``typing`` only at the top).

Covers two sub-packages — all reached through one provider:

* ``infrastructure.persistence.workspaces.models`` — workspace root,
  membership, roles, groups, permissions, preferences, contribution
  means, support impersonation sessions, grant audit events.
* ``infrastructure.persistence.workspaces.workflows.models`` —
  workflow definitions, bindings, runs.
"""

from __future__ import annotations

from typing import Any


class WorkspacesModelsProvider:
    """Lazy accessors for ``infrastructure.persistence.workspaces`` models."""

    # ──────────────────────────────────────────────────────────────────
    # workspaces.models — workspace root + membership/roles/permissions
    # ──────────────────────────────────────────────────────────────────

    @property
    def Workspace(self) -> Any:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace

    @property
    def WorkspaceMembership(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceMembership,
        )

        return WorkspaceMembership

    @property
    def WorkspaceRole(self) -> Any:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        return WorkspaceRole

    @property
    def WorkspaceOperations(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceOperations,
        )

        return WorkspaceOperations

    @property
    def WorkspacePreference(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePreference,
        )

        return WorkspacePreference

    @property
    def WorkspaceGroup(self) -> Any:
        from infrastructure.persistence.workspaces.models import WorkspaceGroup

        return WorkspaceGroup

    @property
    def WorkspaceGroupMembership(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroupMembership,
        )

        return WorkspaceGroupMembership

    @property
    def WorkspacePermissionGrant(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
        )

        return WorkspacePermissionGrant

    @property
    def ContributionMeans(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            ContributionMeans,
        )

        return ContributionMeans

    @property
    def SupportImpersonationSession(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            SupportImpersonationSession,
        )

        return SupportImpersonationSession

    @property
    def GrantAuditEvent(self) -> Any:
        from infrastructure.persistence.workspaces.models import (
            GrantAuditEvent,
        )

        return GrantAuditEvent

    # ──────────────────────────────────────────────────────────────────
    # workspaces.workflows.models
    # ──────────────────────────────────────────────────────────────────

    @property
    def Workflow(self) -> Any:
        from infrastructure.persistence.workspaces.workflows.models import (
            Workflow,
        )

        return Workflow

    @property
    def WorkflowBinding(self) -> Any:
        from infrastructure.persistence.workspaces.workflows.models import (
            WorkflowBinding,
        )

        return WorkflowBinding

    @property
    def WorkflowRun(self) -> Any:
        from infrastructure.persistence.workspaces.workflows.models import (
            WorkflowRun,
        )

        return WorkflowRun


_default = WorkspacesModelsProvider()


def get_workspaces_models_provider() -> WorkspacesModelsProvider:
    """Return the default provider instance.

    Override by monkeypatching this module's ``_default`` attribute in
    tests.
    """
    return _default
