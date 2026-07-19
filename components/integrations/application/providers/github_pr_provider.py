"""Composition root for the GitHub draft-PR capability.

Wires the ``requests``-backed GitHub adapter to the ``GitHubPrPort`` and hands
out a ready ``OpenDraftPrUseCase``. The only application-layer file that knows
the concrete adapter exists (provider files are the allowed composition-root
slot for own-context infrastructure imports).
"""

from __future__ import annotations

from components.integrations.application.ports.github_pr_port import GitHubPrPort
from components.integrations.application.use_cases.open_draft_pr_use_case import OpenDraftPrUseCase


def get_github_pr_adapter(token: str) -> GitHubPrPort:
    from components.integrations.infrastructure.adapters.github_pr_adapter import GitHubPrAdapter

    return GitHubPrAdapter(token)


def get_open_draft_pr_use_case() -> OpenDraftPrUseCase:
    return OpenDraftPrUseCase(adapter_factory=get_github_pr_adapter)
