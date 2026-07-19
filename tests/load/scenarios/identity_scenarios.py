"""Identity surface — login, me/summary, refresh, logout.

Login is exercised in `on_start()` of every authenticated user; this scenario
specifically targets the post-login identity endpoints under load.
"""
from __future__ import annotations

from locust import task

from tests.load.base_users import AuthenticatedHttpUser


class IdentityLoadUser(AuthenticatedHttpUser):
    weight = 2

    @task(5)
    def me_summary(self) -> None:
        self.authed("get", "/identity/me/summary/", name="/identity/me/summary/")

    @task(1)
    def force_refresh(self) -> None:
        # Force a refresh by zeroing the cached expiry and calling _ensure_fresh_token.
        # This stresses /identity/token/refresh/ even within a short run.
        if self._tokens:
            self._tokens.access_expiry_epoch_s = 0.0
        self._ensure_fresh_token()
