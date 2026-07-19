"""Base HttpUser classes for load tests.

`AnonymousHttpUser` — for unauthenticated endpoints (health, schema).
`AuthenticatedHttpUser` — login on start, proactive token refresh, auth header on every task.

Per-context HttpUser subclasses live in `tests/load/scenarios/<ctx>_scenarios.py`
and inherit from these.
"""
from __future__ import annotations

import logging
import time

from locust import HttpUser, between

from tests.load.auth import LoginFailed, Tokens, auth_headers, login, refresh
from tests.load.config import settings

logger = logging.getLogger(__name__)


class AnonymousHttpUser(HttpUser):
    """For unauthenticated endpoints. No login, no token refresh."""

    abstract = True
    wait_time = between(1, 3)
    host = settings.base_url


class AuthenticatedHttpUser(HttpUser):
    """Logs in once, refreshes proactively, sets Authorization header on every request.

    Subclasses define @task methods that call `self.client.get(...)` etc;
    headers are injected automatically via `_default_headers()`.
    """

    abstract = True
    wait_time = between(1, 3)
    host = settings.base_url

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tokens: Tokens | None = None

    def on_start(self) -> None:
        try:
            self._tokens = login(
                self.client,
                email=settings.smoke_email,
                password=settings.smoke_password.get_secret_value(),
            )
        except LoginFailed:
            logger.exception(
                "AuthenticatedHttpUser login failed email=%s — stopping user",
                settings.smoke_email,
            )
            self.environment.runner.quit()
            raise

    def _ensure_fresh_token(self) -> str:
        """Return a valid access token, refreshing if it expires within the buffer window."""
        if self._tokens is None:
            raise RuntimeError("AuthenticatedHttpUser used before on_start completed")
        if (
            self._tokens.access_expiry_epoch_s - time.time()
            < settings.access_token_refresh_buffer_s
        ):
            self._tokens = refresh(self.client, self._tokens.refresh)
        return self._tokens.access

    def authed(self, method: str, url: str, **kwargs):
        """HTTP call with Authorization header set; use instead of self.client.get/post."""
        token = self._ensure_fresh_token()
        headers = {**auth_headers(token), **kwargs.pop("headers", {})}
        return self.client.request(method, url, headers=headers, **kwargs)
