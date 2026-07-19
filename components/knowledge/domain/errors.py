"""Knowledge bounded-context domain errors — pure Python, no framework imports."""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    DomainError as SharedDomainError,
    ValidationError,
)


class DomainError(SharedDomainError):
    """Base error for all Knowledge domain-level invariant violations."""


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
