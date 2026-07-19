from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterUserRequest:
    """Input DTO for POST /register/ endpoint.

    Used to register a new user and send a verification email.
    """
    email: str
    username: str
    password: str
