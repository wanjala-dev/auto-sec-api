"""pydantic-settings config for the RAG eval harness.

Loaded from ``tests/eval/rag/.env.eval`` (gitignored). The sample lives
at ``.env.eval.sample``. Defaults are tuned for a local Docker run
against the seeded Zaylan workspace.

Mirrors the pattern in ``tests/load/config.py`` — keep it close to the
load harness so contributors only learn one config style.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).parent / ".env.eval"


class EvalConfig(BaseSettings):
    """Settings for one eval run.

    Override any field via env var (``EVAL_<FIELD>``) or by editing
    ``.env.eval``. The defaults assume a local Docker stack and the
    seeded Zaylan demo workspace.
    """

    model_config = SettingsConfigDict(
        env_prefix="EVAL_",
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Target system under test ───────────────────────────────────────
    target: Literal["local", "demo"] = "local"
    workspace_uuid: str = Field(
        default="",
        description=(
            "UUID of the workspace the eval runs against. Required. "
            "For local + Zaylan, find it via `docker exec compose-web-1 "
            "python manage.py shell -c \"from "
            "infrastructure.persistence.workspaces.models import "
            "Workspace; print(Workspace.objects.get("
            "workspace_name='Zaylan').id)\"`."
        ),
    )
    user_uuid: str = Field(
        default="",
        description=(
            "UUID of the user the eval runs as. Required. Should be the "
            "Zaylan founder so the chat path uses an owner-role membership."
        ),
    )

    # ── Eval set and reports ───────────────────────────────────────────
    eval_set_path: Path = Path(__file__).parent / "eval_set.yaml"
    reports_dir: Path = Path(__file__).parent / "reports"

    # ── Judge LLM ──────────────────────────────────────────────────────
    judge_model: str = "gpt-4o-mini"
    judge_temperature: float = 0.0
    judge_max_tokens: int = 1024
    judge_cache_path: Path = (
        Path(__file__).parent / "reports" / ".judge_cache.json"
    )

    # ── Subject-under-test LLM (the chat path) ─────────────────────────
    # Leave blank to use the workspace's configured model. Override for
    # A/B experiments (e.g. compare gpt-4o vs claude-sonnet for chat).
    chat_model: str = ""

    # ── Run controls ───────────────────────────────────────────────────
    # When True, the runner only emits the collected run record (no
    # judge LLM calls). Useful for cheap pipeline-only checks.
    collect_only: bool = False
    # When True, runs are wholly deterministic (no chat path call) and
    # the runner reads an existing collected run record from
    # ``replay_run_path``. Pair with judge_cache to make scoring free.
    score_only: bool = False
    replay_run_path: Path = Path()
    # Limit run to the first N prompts for fast iteration. 0 = all.
    max_prompts: int = 0
    # Categories to include (empty = all).
    only_categories: tuple[str, ...] = ()


def base_url_for(target: Literal["local", "demo"]) -> str:
    """Resolve the HTTP base URL for ``target``.

    Matches the load harness's ``config.base_url`` helper so external
    eval against demo is one env-var flip from local.
    """
    if target == "demo":
        return "https://api.wanjala.art"
    return "http://localhost:8000"


def load() -> EvalConfig:
    """Load the eval config from env + ``.env.eval``.

    Validates that workspace_uuid + user_uuid are set; without them the
    runner can't dispatch the chat path. Raises a clear error rather
    than letting the runner blow up mid-call.
    """
    cfg = EvalConfig()
    missing: list[str] = []
    if not cfg.workspace_uuid:
        missing.append("EVAL_WORKSPACE_UUID")
    if not cfg.user_uuid:
        missing.append("EVAL_USER_UUID")
    if missing:
        raise RuntimeError(
            "RAG eval harness is missing required config: "
            + ", ".join(missing)
            + ". Set them in tests/eval/rag/.env.eval (copy from "
            ".env.eval.sample) or as environment variables."
        )
    return cfg
