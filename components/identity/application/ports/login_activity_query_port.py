"""Port for reading auth-audit (login-activity) feeds.

Framework-free interface. The ORM adapter returns lazily-evaluated,
sliceable sequences (in practice Django querysets with ``session`` —
and, for workspace reads, ``user`` — eager-loaded) so the REST adapter
can paginate without materialising the whole feed — the application
layer only depends on this abstract shape.

Two read scopes share the port so the filter logic lives in ONE
repository:

- self scope (``list_for_user``) — the caller's own trail (T2-S3).
- workspace scope (T2-S4) — an org admin's view over the ACTIVE
  members' login-ish events, minus the workspace's exclusions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from components.identity.application.queries.login_activity_query import LoginActivityQuery
from components.identity.application.queries.workspace_login_activity_query import WorkspaceLoginActivityQuery


class LoginActivityQueryPort(ABC):
    """Secondary/driven port for the login-activity read model."""

    @abstractmethod
    def list_for_user(self, query: LoginActivityQuery) -> Sequence:
        """Return the user's audit events, newest first, filtered per
        ``query``. Must be sliceable (paginator-friendly) and MUST
        eager-load each event's linked session."""

    @abstractmethod
    def list_for_workspace(self, query: WorkspaceLoginActivityQuery) -> Sequence:
        """Return the login-ish audit events of the workspace's ACTIVE
        members (including the workspace owner even without a membership
        row), newest first, MINUS the events excluded for this workspace.
        Must be sliceable and MUST eager-load each event's linked
        ``session`` and ``user``."""

    @abstractmethod
    def list_active_workspace_sessions(self, *, workspace_id: UUID, limit: int = 200) -> Sequence:
        """Return the ACTIVE members' active login sessions (not revoked,
        not expired; owner included), ordered by most recently seen,
        capped at ``limit`` rows, with the owning ``user`` eager-loaded."""

    @abstractmethod
    def get_workspace_event(self, *, workspace_id: UUID, event_id: int):
        """Return one login-ish audit event if it belongs to an ACTIVE
        member (or the owner) of the workspace, else ``None``. Does NOT
        apply the workspace's exclusions — already-hidden events still
        resolve so hide requests stay idempotent."""
