"""Command and result value objects for the change-password flow."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class ChangePasswordCommand:
    user_id: UUID
    email: str
    old_password: str
    new_password: str
    confirm_password: str
    context: RequestContext


@dataclass(frozen=True)
class ChangePasswordResult:
    success: bool
    message: str


@dataclass(frozen=True)
class ChangePasswordFailure:
    field: str
    messages: list[str]
