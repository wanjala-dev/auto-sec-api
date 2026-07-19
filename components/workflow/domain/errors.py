"""Domain errors for the workflow bounded context.

No Django / DRF imports — extends the shared kernel taxonomy.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class WorkflowError(DomainError):
    """Base class for all workflow domain errors."""


class WorkflowNotFoundError(WorkflowError, NotFoundError):
    """Raised when a workflow cannot be found."""


class WorkflowTemplateNotFoundError(WorkflowError, NotFoundError):
    """Raised when a workflow template cannot be found."""


class WorkflowRunNotFoundError(WorkflowError, NotFoundError):
    """Raised when a workflow run cannot be found."""


class WorkflowBindingNotFoundError(WorkflowError, NotFoundError):
    """Raised when a workflow binding cannot be found."""


class WorkflowGraphValidationError(WorkflowError, ValidationError):
    """Raised when a workflow graph fails structural validation."""


class WorkflowStatusError(WorkflowError, ValidationError):
    """Raised when a workflow is in the wrong status for the requested operation."""


class WorkflowPermissionError(WorkflowError, AuthorizationError):
    """Raised when a user lacks permission for a workflow operation."""


class WorkflowRunStatusError(WorkflowError, ValidationError):
    """Raised when a workflow run is in the wrong status for the requested action."""


class WorkflowNodeNotFoundError(WorkflowError, NotFoundError):
    """Raised when a node does not exist in a workflow graph."""


class WorkflowIdempotencyError(WorkflowError, ConflictError):
    """Raised when an idempotency check fails for a workflow run."""


class WorkflowActionError(WorkflowError):
    """Raised when a workflow action node fails to execute.

    The engine treats this as a hard failure: the run is marked FAILED and the
    failure is logged with run/node ids. Action executors MUST raise this (or any
    exception) on a genuine failure rather than swallowing it — a silently
    "completed" step that never sent its email is the bug this prevents.
    """


class WorkflowConditionError(WorkflowError, ValidationError):
    """Raised when a condition node's predicate is malformed and cannot be evaluated."""
