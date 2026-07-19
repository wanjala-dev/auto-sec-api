"""Domain errors for the sign-off kernel.

Kept framework-free (no Django / DRF imports) per the architecture manifesto —
the API layer maps these to HTTP responses via the shared exception handler.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import ConflictError, DomainError, NotFoundError


class SignOffError(DomainError):
    """Base error for the sign-off kernel."""


class IllegalTransitionError(SignOffError, ConflictError):
    """Raised when a review-state transition is not allowed.

    Example: approving an already-rejected artifact, or any transition out of a
    terminal state.
    """

    def __init__(self, src, dst) -> None:
        self.src = src
        self.dst = dst
        super().__init__(f"illegal review-state transition: {src} -> {dst}")


class NotApprovedError(SignOffError, ConflictError):
    """Raised by ``require_approved`` when a downstream send/apply action is
    attempted on an artifact that has not been signed off.

    This is the kernel's teeth: every "it goes out / gets applied" code path
    calls ``require_approved`` first, and this error blocks the action when the
    artifact is still pending / had changes requested / was rejected.
    """

    def __init__(self, artifact_type: str, artifact_id: str, state) -> None:
        self.artifact_type = artifact_type
        self.artifact_id = artifact_id
        self.state = state
        super().__init__(
            f"{artifact_type} {artifact_id} is not approved (state={state}); "
            "a human must sign off before it can be sent or applied"
        )


class UnregisteredArtifactError(SignOffError, NotFoundError):
    """Raised when no sign-off adapter is registered for an artifact type."""

    def __init__(self, artifact_type: str) -> None:
        self.artifact_type = artifact_type
        super().__init__(f"no sign-off adapter registered for artifact_type={artifact_type!r}")
