from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleSocialAuthRequest:
    """Input DTO for POST /google/ endpoint.

    Used to authenticate via Google social login with auth token.
    """
    auth_token: str
