"""AI bounded-context domain errors — pure Python, no framework imports."""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    DomainError as SharedDomainError,
    ValidationError,
)


class DomainError(SharedDomainError):
    """Base error for all AI domain-level invariant violations."""


class UnsupportedProviderError(DomainError, ValidationError):
    """Raised when a requested provider slug has no registered adapter."""

    def __init__(self, kind: str, provider: str, available: list[str]) -> None:
        self.kind = kind
        self.provider = provider
        self.available = available
        super().__init__(
            f"Unsupported {kind} provider: '{provider}'. "
            f"Available: {', '.join(sorted(available))}"
        )


class AgentNotFoundError(DomainError, LookupError):
    """Raised when an agent or related record cannot be found."""


class AgentDisabledError(DomainError):
    """Raised when an agent profile is disabled."""


class AgentPermissionError(DomainError):
    """Raised when a user lacks the required agent permission."""


class AgentEngagementError(DomainError, ValidationError):
    """Raised for engagement validation failures (ratings disabled, comments disabled, etc.)."""


class ShareNotFoundError(DomainError, LookupError):
    """Raised when a share token is not found or expired."""


class InvalidCommentError(DomainError, ValidationError):
    """Raised for comment validation failures (invalid parent, max depth, etc.)."""


class InvalidShareScopeError(DomainError, ValidationError):
    """Raised when an invalid share scope is provided."""


class AiRunLimitExceeded(DomainError):
    """Raised when a workspace has used its monthly metered-AI allowance.

    Metered AI (Free/Pro/Premium): one-shot ``execute`` runs and ``deep_run``
    plans/runs both count against ``MAX_AI_RUNS_PER_MONTH``; conversational
    ``chat`` does not. The controller maps this to HTTP 402 with an
    upgrade nudge. ``used`` / ``limit`` are carried so the response can show
    "20 / 20 runs used — upgrade to Pro for 200".
    """

    def __init__(self, *, used: int, limit: int, workspace_id: str | None = None) -> None:
        self.used = used
        self.limit = limit
        self.workspace_id = workspace_id
        super().__init__(
            f"Monthly AI-run limit reached ({used}/{limit}). "
            "Upgrade your plan for a higher allowance."
        )


class AiUnavailable(DomainError):
    """Raised when the emergency AI kill switch is engaged (SEE-202).

    An operator has tripped ``feature.ai_kill_switch`` (globally or for one
    workspace) to halt AI execution without a deploy. The controller maps this
    to HTTP 503 — the condition is transient and operator-controlled, not a
    client error and not a billing/upgrade nudge.
    """

    def __init__(self, *, workspace_id: str | None = None, message: str | None = None) -> None:
        self.workspace_id = workspace_id
        super().__init__(message or "AI is temporarily unavailable. Please try again shortly.")
