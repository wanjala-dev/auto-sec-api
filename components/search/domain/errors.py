"""Domain errors for the search bounded context."""

from __future__ import annotations

from components.shared_kernel.domain.errors import AuthorizationError, DomainError


class SearchError(DomainError):
    """Base class for search-context errors."""


class WorkspaceAccessDenied(AuthorizationError):
    """Raised when the requester asks to search a workspace they are not an
    active member of. The API adapter maps this to HTTP 403."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        super().__init__(f"Requester is not an active member of workspace {workspace_id}")
