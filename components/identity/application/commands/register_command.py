"""Command and result value objects for the register use case.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RegisterCommand:
    """Input for the register use case."""

    username: str
    email: str
    password: str
    site_name: str
    site_domain: str
    confirmation_base_url: str


@dataclass(frozen=True)
class RegisterResult:
    """Output of a successful registration."""

    user_id: UUID
    email: str
    username: str
    email_sent: bool
    warning: str | None = None
