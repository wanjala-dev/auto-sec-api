"""Composition root + registry for the VCS draft-PR capability (ADR 0010).

``provider -> VcsPort`` adapter, exactly like ``LogSourceProvider``'s ``kind ->
adapter``. The only application-layer file that knows the concrete adapters exist
(provider files are the allowed composition-root slot for own-context infrastructure
imports). GitHub is the shipped adapter; GitLab/Bitbucket land here behind
``feature.vcs_gitlab`` / ``feature.vcs_bitbucket`` when their adapters ship (D4).
"""

from __future__ import annotations

from collections.abc import Callable

from components.integrations.application.ports.vcs_port import VcsPort
from components.integrations.application.use_cases.open_draft_pr_use_case import OpenDraftPrUseCase


class UnsupportedVcsProviderError(Exception):
    """The requested VCS provider has no registered/enabled adapter."""


def _github_adapter(token: str) -> VcsPort:
    from components.integrations.infrastructure.adapters.vcs.github_vcs_adapter import GitHubVcsAdapter

    return GitHubVcsAdapter(token)


# provider -> adapter factory (the registry). GitLab/Bitbucket are added here behind
# their feature flags once built — until then an unknown provider fails closed.
_ADAPTER_FACTORIES: dict[str, Callable[[str], VcsPort]] = {
    "github": _github_adapter,
}


def get_vcs_adapter(provider: str, token: str) -> VcsPort:
    """Resolve the adapter for a provider. Raises :class:`UnsupportedVcsProviderError`
    for a provider with no enabled adapter (fail closed)."""
    factory = _ADAPTER_FACTORIES.get((provider or "").strip().lower())
    if factory is None:
        raise UnsupportedVcsProviderError(f"No enabled VCS adapter for provider '{provider}'.")
    return factory(token)


def get_finding_facts_reader():
    """Composition root for the read-side board access (C3): the use case reads a
    finding's board Task through this port, never ``project``'s ORM."""
    from components.integrations.infrastructure.adapters.board_finding_facts_reader import (
        BoardFindingFactsReader,
    )

    return BoardFindingFactsReader()


def get_finding_pr_recorder():
    """Composition root for the write-side board access (C2): the draft-PR record
    is ``project.Task`` data, so this adapter delegates the write to ``project``."""
    from components.integrations.infrastructure.adapters.project_finding_pr_recorder import (
        ProjectFindingPrRecorder,
    )

    return ProjectFindingPrRecorder()


def get_open_draft_pr_use_case() -> OpenDraftPrUseCase:
    # The use case reads the VcsConnection and passes its ``provider``; the registry
    # resolves the matching adapter (Phase 2). ``get_vcs_adapter`` is ``(provider, token)``.
    # The board read/write ports are wired here (C2/C3) so the application layer holds
    # no direct infrastructure import.
    return OpenDraftPrUseCase(
        adapter_factory=get_vcs_adapter,
        finding_facts=get_finding_facts_reader(),
        pr_recorder=get_finding_pr_recorder(),
    )


def get_vcs_connection_service():
    """Composition root for the VcsConnection lifecycle service (ADR 0010 Phase 3) —
    wires the repository, the adapter registry (for verify), and the secret envelope.
    Controllers resolve this and stay ORM/SDK/crypto-free."""
    from components.integrations.application.providers.secret_envelope_provider import (
        decrypt_secret,
        encrypt_secret,
    )
    from components.integrations.application.vcs_connection_service import VcsConnectionService
    from components.integrations.infrastructure.repositories.vcs_connection_repository import (
        VcsConnectionRepository,
    )

    return VcsConnectionService(
        _repo=VcsConnectionRepository(),
        _resolve_adapter=get_vcs_adapter,
        _encrypt=encrypt_secret,
        _decrypt=decrypt_secret,
    )
