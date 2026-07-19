"""Load-test configuration. See `.claude/rules/load-testing.md` for the rules.

Single source of truth for env-driven settings. Scenarios import the resolved
values from here; they never read environment variables directly.

Env vars (loaded from `tests/load/.env.load` or process env):
    LOAD_TARGET=local|demo            (default: local — never accidentally hit demo)
    LOAD_PROFILE=smoke|avg|spike|stress|soak
    LOAD_LOCAL_BASE_URL=http://localhost:8000
    LOAD_DEMO_BASE_URL=https://api.wanjala.art
    LOAD_SMOKE_EMAIL=admin@test.octopi.dev
    LOAD_SMOKE_PASSWORD=<persona password>
    LOAD_SMOKE_WORKSPACE_ID=<uuid>     (optional; if absent, scenario lists workspaces and picks first)
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_HERE = Path(__file__).resolve().parent
_ENV_FILE = _HERE / ".env.load"


class LoadSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_prefix="LOAD_",
        extra="ignore",
        case_sensitive=False,
    )

    target: Literal["local", "demo"] = "local"
    profile: Literal["smoke", "avg", "spike", "stress", "soak"] = "smoke"

    local_base_url: str = "http://localhost:8000"
    demo_base_url: str = "https://api.wanjala.art"

    smoke_email: str = "admin@test.octopi.dev"
    smoke_password: SecretStr = SecretStr("")
    smoke_workspace_id: str | None = None

    request_timeout_s: float = 10.0
    access_token_refresh_buffer_s: int = 60

    @property
    def base_url(self) -> str:
        if self.target == "demo":
            return self.demo_base_url
        return self.local_base_url


settings = LoadSettings()
