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


def resolve_vcs_connection_token(connection) -> str:
    """The ONE per-connection credential strategy (ADR 0010 Phase B).

    PAT rows decrypt the stored envelope ciphertext (the Phase-A behavior,
    unchanged); ``auth_mode == github_app`` rows mint a short-lived installation
    token from the app credentials — the stored PAT ciphertext is never read in
    app mode. Every seam that turns a ``VcsConnection`` into a runtime token is
    wired to THIS resolver so the strategy cannot fork per call site. Raises the
    typed revoked/not-configured errors (``VcsApiError`` subclasses) for
    app-mode failures the connection layer must act on."""
    from components.integrations.infrastructure.adapters.connection_token_resolver import (
        resolve_connection_token,
    )

    return resolve_connection_token(connection)


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


def resolve_vcs_connection(workspace_id: str):
    """Resolve the workspace's most-recent ``VcsConnection`` (own-context ORM read).

    The composition root owns this read (Rule 9) so the draft-PR use case holds no
    persistence import. Most-recent connection wins — the same resolution the
    ``_require_connection`` gate did inline (a per-repo refinement is Phase 3 work).
    The status gate stays in the use case; this returns the row (or ``None``)."""
    from infrastructure.persistence.integrations.models import VcsConnection

    return VcsConnection.objects.filter(workspace_id=str(workspace_id)).order_by("-created_at").first()


def resolve_workspace_owner_id(workspace_id: str) -> str | None:
    """Resolve a workspace's owner user id for the draft-PR HITL notification.

    Cross-context read routed through the composition root — the use case never
    imports ``workspaces`` persistence. Returns the id as a string, or ``None``."""
    from infrastructure.persistence.workspaces.models import Workspace

    owner_id = Workspace.objects.filter(id=str(workspace_id)).values_list("workspace_owner_id", flat=True).first()
    return str(owner_id) if owner_id is not None else None


def resolve_operator_identity(user_id: str) -> dict | None:
    """Resolve the approving operator's commit identity (name + email only).

    Cross-context read routed through the composition root — the use case never
    imports ``users`` persistence, and only the two non-secret attribution fields
    cross back (never the ORM user). ``name`` is ``get_full_name()`` falling back to
    ``username`` (may be empty — the caller then falls back to the email); ``email``
    is the raw address. Returns ``None`` when the user row is absent."""
    from infrastructure.persistence.users.models import CustomUser

    user = CustomUser.objects.filter(id=str(user_id)).first()
    if user is None:
        return None
    name = (user.get_full_name() or "").strip() or (user.username or "").strip()
    email = (getattr(user, "email", "") or "").strip()
    return {"name": name, "email": email}


def get_finding_preview_recorder():
    """Composition root for the preview board write (C2, ADR 0012 P6): the proposed-fix
    preview is ``project.Task`` data, so this adapter delegates the write to ``project``."""
    from components.integrations.infrastructure.adapters.project_finding_preview_recorder import (
        ProjectFindingPreviewRecorder,
    )

    return ProjectFindingPreviewRecorder()


def get_open_draft_pr_use_case() -> OpenDraftPrUseCase:
    # The use case reads the VcsConnection and passes its ``provider``; the registry
    # resolves the matching adapter (Phase 2). ``get_vcs_adapter`` is ``(provider, token)``.
    # EVERY ORM-backed dependency is wired here (the composition root) so the use case
    # holds no persistence import:
    #   * board read/write        → C2/C3 finding ports
    #   * VcsConnection resolve    → resolve_vcs_connection (own-context)
    #   * token decrypt            → decrypt_secret (secret envelope)
    #   * triage capability port   → agents' AgentCapabilityPort (#216)
    #   * workspace owner / operator identity → provider resolvers (cross-context)
    from components.agents.application.providers.ai_provider import AIProvider
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret

    return OpenDraftPrUseCase(
        adapter_factory=get_vcs_adapter,
        finding_facts=get_finding_facts_reader(),
        pr_recorder=get_finding_pr_recorder(),
        resolve_connection=resolve_vcs_connection,
        decrypt=decrypt_secret,
        # Auth strategy (Phase B): the connection-aware resolver supersedes the
        # raw decrypt above wherever a token is minted; `decrypt` stays wired as
        # the injected fallback for tests that fake it.
        resolve_token=resolve_vcs_connection_token,
        capability_port=AIProvider.build_agent_capability_port(),
        resolve_workspace_owner_id=resolve_workspace_owner_id,
        resolve_operator_identity=resolve_operator_identity,
        preview_recorder=get_finding_preview_recorder(),
        # grounding_retrieval defaults to None → resolved lazily via the remediation
        # provider inside retrieve_grounding_sources (P6 preview display).
    )


def get_check_pr_merged_use_case():
    """Composition root for the PR-merge check (ADR 0012 P4a) — wires the connection
    resolver, the secret envelope, and the adapter registry. The remediation
    reconciler resolves this through the integrations *application* layer and stays
    free of any VCS infra/SDK import."""
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
    from components.integrations.application.use_cases.check_pull_request_merged_use_case import (
        CheckPullRequestMergedUseCase,
    )

    def _resolve_connection(workspace_id: str):
        # Most-recent connected VcsConnection for the workspace wins — same
        # resolution the draft-PR use case uses (a per-repo refinement is future work).
        from infrastructure.persistence.integrations.models import VcsConnection

        return (
            VcsConnection.objects.filter(workspace_id=workspace_id, status=VcsConnection.Status.CONNECTED)
            .order_by("-created_at")
            .first()
        )

    return CheckPullRequestMergedUseCase(
        resolve_connection=_resolve_connection,
        decrypt=decrypt_secret,
        resolve_adapter=get_vcs_adapter,
        resolve_token=resolve_vcs_connection_token,
    )


def get_backfill_draft_pr_patches_use_case():
    """Composition root for the legacy draft-PR patch backfill.

    Wires the same three seams the merge-check read uses (connection resolver,
    secret envelope, adapter registry) plus the two board ports the open step
    uses — the C3 read that finds patch-less records and the C2 recorder that
    writes the patch back through ``project``. The CLI command holds no ORM,
    crypto, or SDK import."""
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
    from components.integrations.application.use_cases.backfill_draft_pr_patches_use_case import (
        BackfillDraftPrPatchesUseCase,
    )

    return BackfillDraftPrPatchesUseCase(
        finding_facts=get_finding_facts_reader(),
        pr_recorder=get_finding_pr_recorder(),
        resolve_connection=resolve_vcs_connection,
        decrypt=decrypt_secret,
        resolve_adapter=get_vcs_adapter,
        resolve_token=resolve_vcs_connection_token,
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
        _resolve_token=resolve_vcs_connection_token,
    )
