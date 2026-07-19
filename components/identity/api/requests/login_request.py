from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LoginRequest:
    """Input DTO for POST /login/ endpoint.

    Used to authenticate a user and return tokens with onboarding flags.
    """
    email: str
    password: str
