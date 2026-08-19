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

# Mirrors ``VcsConnection.Status.CONNECTED`` without importing persistence at module
# scope (same constant the draft-PR use case gates on).
_STATUS_CONNECTED = "connected"


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


def _non_empty_allowlist(connection) -> list[str]:
    """The connection's allowlisted repos, normalised (blank/non-string entries dropped)."""
    raw = getattr(connection, "repo_allowlist", None) or []
    return [r.strip() for r in raw if isinstance(r, str) and r.strip()]


def resolve_vcs_connection(workspace_id: str, *, repo: str = ""):
    """Resolve the ``VcsConnection`` that can actually serve ``repo`` for this workspace.

    The composition root owns this read (Rule 9) so the draft-PR use case holds no
    persistence import. ``VcsConnection`` is deliberately a **many-rows-per-workspace**
    model (see the model docstring: an org can link GitHub *and* GitLab, each with its
    own ``repo_allowlist``), so "most-recent row wins" was never a safe resolution — it
    let ANY newer row silently take over the workspace's whole draft-PR capability:

    * completing the GitHub App install flow writes a second ``connected`` row whose
      allowlist is deliberately empty → every finding started refusing with
      ``repo_not_allowlisted``;
    * a connection whose ``verify`` failed goes ``status=error`` → every finding
      refused with ``connection_not_connected``;
    * a connection for a different repo won over the one that allowlists the
      finding's repo → ``finding_repo_not_allowlisted`` for a repo that IS allowlisted.

    Preference order, newest-first within each tier:

    1. a CONNECTED row whose allowlist contains ``repo`` (the consent-exact match);
    2. a CONNECTED row with a non-empty allowlist (can serve *some* PR);
    3. any CONNECTED row;
    4. the newest row of any status — so a workspace whose only connection is broken
       still gets the accurate ``connection_not_connected`` diagnostic from the caller's
       status gate rather than a misleading "no connection at all".

    The status gate itself stays in the caller; this returns the row (or ``None``)."""
    from infrastructure.persistence.integrations.models import VcsConnection

    rows = list(VcsConnection.objects.filter(workspace_id=str(workspace_id)).order_by("-created_at"))
    if not rows:
        return None

    connected = [r for r in rows if r.status == VcsConnection.Status.CONNECTED]
    target = (repo or "").strip()
    if target:
        for row in connected:
            if target in _non_empty_allowlist(row):
                return row
    for row in connected:
        if _non_empty_allowlist(row):
            return row
    return connected[0] if connected else rows[0]


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
        # ONE canonical resolution shared with the draft-PR path (dry-reuse): this
        # seam used to run its own `status=CONNECTED` ORM read, so the two disagreed
        # about which row served a workspace — the drift that let a newer empty /
        # errored row shadow the healthy connection. Only the CONNECTED gate is kept
        # local, because this caller reports "no connection" rather than a status.
        connection = resolve_vcs_connection(workspace_id)
        if connection is None or connection.status != _STATUS_CONNECTED:
            return None
        return connection

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
