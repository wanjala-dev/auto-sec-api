"""Open a DRAFT GitHub PR for a triaged log-error finding (Phase A, rung 1).

The single choke point for the triage agent's draft-PR capability. EVERY
precondition is enforced here — the agent tool and the HITL endpoint are thin
callers, so neither path can skip a gate:

1. A ``GitHubConnection`` exists for the workspace and is ``connected``.
2. The target repo is on the connection's ``repo_allowlist`` (consent boundary).
3. The finding exists, is ``ai.log_watch``, is triaged, and is NOT
   ``needs_human`` (the grounded-verifier precondition — an ungrounded fix
   never becomes a PR).
4. The workspace's triage agent row has
   ``config.capabilities.open_draft_pr == true``.

Idempotent: a finding that already carries ``payload.draft_pr`` returns the
existing PR without touching the GitHub API. Failures raise
:class:`DraftPrPreconditionError` with a machine-readable ``reason`` — never
silent. VCS provider API failures propagate as ``VcsApiError``.

Rung 1 (HITL): ``performed_by`` is the approving human's user id; the tool's
``irreversible`` risk tier denies autonomous runs before this code is reached.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from components.integrations.application.log_patch_advisor_service import (
    LogPatchAdvisor,
    PatchValidationError,
    RepoPathResolutionError,
    derive_candidate_path,
    resolve_repo_path,
    validate_patch,
)
from components.integrations.application.ports.finding_facts_port import (
    ActionableFinding,
    FindingFactsPort,
)
from components.integrations.application.ports.finding_pr_recorder_port import (
    FindingPrRecorderPort,
)
from components.integrations.application.ports.vcs_port import VcsApiError, VcsPort

logger = logging.getLogger(__name__)

_LOG_WATCH_SOURCE = "ai.log_watch"
_ACTING_AGENT = "triage_agent"

# VcsConnection status/commit-identity values. Kept as string literals so the
# application layer needs no ORM import to compare them — they mirror the enum
# TextChoices on ``infrastructure.persistence.integrations.models.VcsConnection``.
_STATUS_CONNECTED = "connected"
_COMMIT_IDENTITY_OPERATOR = "operator"
_COMMIT_IDENTITY_CUSTOM = "custom"


class DraftPrPreconditionError(Exception):
    """A draft-PR precondition failed. ``reason`` is a stable machine code."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class DraftPrResult:
    url: str
    repo: str
    branch: str
    created: bool  # False → idempotent hit (PR already existed)


class OpenDraftPrUseCase:
    def __init__(
        self,
        adapter_factory: Callable[[str, str], VcsPort],  # (provider, token) -> adapter
        advisor: LogPatchAdvisor | None = None,
        finding_facts: FindingFactsPort | None = None,
        pr_recorder: FindingPrRecorderPort | None = None,
        resolve_connection: Callable[[str], object | None] | None = None,
        decrypt: Callable[[str], str] | None = None,
        capability_port: AgentCapabilityPort | None = None,
        resolve_workspace_owner_id: Callable[[str], str | None] | None = None,
        resolve_operator_identity: Callable[[str], dict | None] | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._advisor = advisor or LogPatchAdvisor()
        # Every cross-context / own-context READ goes through a port or an
        # injected resolver (C2/C3 + Rule 2). Defaults are resolved lazily from
        # the provider — the composition root that owns the ORM — so the
        # application layer holds no direct infrastructure import:
        #   * board read/write   → FindingFactsPort / FindingPrRecorderPort
        #   * VcsConnection (own) → resolve_connection (mirrors the sibling
        #     CheckPullRequestMergedUseCase; the row is resolved in the provider)
        #   * token ciphertext    → decrypt (a runtime credential produced by the
        #     injected secret-envelope callable; never a port return value)
        #   * triage capability   → AgentCapabilityPort (#216, agents context)
        #   * workspace owner id  → resolve_workspace_owner_id
        #   * operator identity   → resolve_operator_identity (name/email only)
        self._finding_facts = finding_facts
        self._pr_recorder = pr_recorder
        self._resolve_connection = resolve_connection
        self._decrypt = decrypt
        self._capability_port = capability_port
        self._resolve_workspace_owner_id = resolve_workspace_owner_id
        self._resolve_operator_identity = resolve_operator_identity

    def _finding_facts_port(self) -> FindingFactsPort:
        if self._finding_facts is None:
            from components.integrations.application.providers.vcs_provider import (
                get_finding_facts_reader,
            )

            self._finding_facts = get_finding_facts_reader()
        return self._finding_facts

    def _pr_recorder_port(self) -> FindingPrRecorderPort:
        if self._pr_recorder is None:
            from components.integrations.application.providers.vcs_provider import (
                get_finding_pr_recorder,
            )

            self._pr_recorder = get_finding_pr_recorder()
        return self._pr_recorder

    def _resolve_connection_fn(self) -> Callable[[str], object | None]:
        if self._resolve_connection is None:
            from components.integrations.application.providers.vcs_provider import (
                resolve_vcs_connection,
            )

            self._resolve_connection = resolve_vcs_connection
        return self._resolve_connection

    def _decrypt_fn(self) -> Callable[[str], str]:
        if self._decrypt is None:
            from components.integrations.application.providers.secret_envelope_provider import (
                decrypt_secret,
            )

            self._decrypt = decrypt_secret
        return self._decrypt

    def _capability_port_(self) -> AgentCapabilityPort:
        if self._capability_port is None:
            from components.agents.application.providers.ai_provider import AIProvider

            self._capability_port = AIProvider.build_agent_capability_port()
        return self._capability_port

    def _resolve_workspace_owner_id_fn(self) -> Callable[[str], str | None]:
        if self._resolve_workspace_owner_id is None:
            from components.integrations.application.providers.vcs_provider import (
                resolve_workspace_owner_id,
            )

            self._resolve_workspace_owner_id = resolve_workspace_owner_id
        return self._resolve_workspace_owner_id

    def _resolve_operator_identity_fn(self) -> Callable[[str], dict | None]:
        if self._resolve_operator_identity is None:
            from components.integrations.application.providers.vcs_provider import (
                resolve_operator_identity,
            )

            self._resolve_operator_identity = resolve_operator_identity
        return self._resolve_operator_identity

    def execute(
        self,
        *,
        workspace_id: str,
        task_id: str,
        performed_by: str,
        repo: str | None = None,
    ) -> DraftPrResult:
        connection = self._require_connection(workspace_id)
        target_repo = self._require_allowlisted_repo(connection, repo)
        task = self._require_actionable_finding(workspace_id, task_id)

        payload = (task.metadata or {}).get("payload") or {}
        existing = payload.get("draft_pr") or {}
        if existing.get("url"):
            # Idempotent: the PR already exists — return it, zero API calls.
            return DraftPrResult(
                url=existing["url"],
                repo=existing.get("repo") or target_repo,
                branch=existing.get("branch") or "",
                created=False,
            )

        self._require_capability(workspace_id)

        token = self._decrypt_token(connection)
        candidate_path = derive_candidate_path(payload)
        if not candidate_path:
            raise DraftPrPreconditionError(
                "no_candidate_path",
                "The finding's evidence names no source file — cannot derive a patch target.",
            )

        adapter = self._adapter_factory(getattr(connection, "provider", ""), token)
        default_branch = adapter.get_default_branch(target_repo)
        resolved_path, repo_file = self._resolve_and_fetch(
            adapter=adapter,
            target_repo=target_repo,
            ref=default_branch.name,
            candidate_path=candidate_path,
            explicit_prefix=(getattr(connection, "repo_root", "") or "").strip(),
        )

        # ADR 0012 P4: ground the patch in the team's vetted prior fixes for this
        # class of finding BEFORE the advisor proposes. Grounding never authorizes —
        # ``validate_patch`` below still runs on whatever comes back (D2).
        proposal = self._advisor.propose(
            payload=payload,
            path=resolved_path,
            current_content=repo_file.content,
            workspace_id=str(workspace_id),
            source_type=_LOG_WATCH_SOURCE,
        )
        if proposal is None:
            raise DraftPrPreconditionError(
                "no_grounded_patch",
                "No grounded patch could be generated from the finding's evidence.",
            )

        # Verification above the model: FAIL CLOSED before any branch/commit/PR.
        # A destructive or broken patch (e.g. the advisor gutting the file it was
        # asked to fix) never reaches GitHub — it raises a typed precondition the
        # controller maps to 422. Composes with no_grounded_patch above.
        try:
            validate_patch(
                original_content=repo_file.content,
                updated_content=proposal.updated_content,
                path=proposal.path,
            )
        except PatchValidationError as exc:
            raise DraftPrPreconditionError(exc.reason, str(exc)) from exc

        branch = f"autosec/finding-{task_id}"
        title = f"[Auto-Sec] {task.title[:180]}"
        commit_author = self._resolve_commit_author(connection, performed_by)
        adapter.create_branch(target_repo, branch, from_sha=default_branch.head_sha)
        adapter.commit_file(
            target_repo,
            branch,
            proposal.path,
            proposal.updated_content,
            message=title,
            file_sha=repo_file.sha,
            author=commit_author,
        )
        pr = adapter.open_draft_pr(
            target_repo,
            head=branch,
            base=default_branch.name,
            title=title,
            body=self._build_pr_body(task, payload, proposal),
        )

        # C2: the finding-provenance write is ``project.Task`` data → delegate to
        # ``project`` (which owns it) through the recorder port. Same contract as
        # before: patches ``metadata.payload.draft_pr``, appends the provenance
        # event, and adds the card comment — so the HUD still renders the PR on the
        # card (every AI action shows on the board).
        self._pr_recorder_port().record_draft_pr(
            workspace_id=workspace_id,
            task_id=task_id,
            performed_by=performed_by,
            acting_agent=_ACTING_AGENT,
            pr_url=pr.url,
            pr_repo=pr.repo,
            branch=branch,
        )
        self._notify_draft_pr_opened(
            workspace_id=workspace_id,
            task=task,
            performed_by=performed_by,
            pr_url=pr.url,
            repo=target_repo,
        )
        logger.info(
            "open_draft_pr opened task_id=%s workspace_id=%s repo=%s pr=%s performed_by=%s",
            task_id,
            workspace_id,
            target_repo,
            pr.url,
            performed_by,
        )
        return DraftPrResult(url=pr.url, repo=target_repo, branch=branch, created=True)

    def _resolve_and_fetch(self, *, adapter, target_repo, ref, candidate_path, explicit_prefix):
        """Resolve ``candidate_path`` to its real repo path and fetch its content.

        Fast path (repo-root apps): try ``get_file(candidate_path)`` FIRST — one call,
        no tree fetch. Only when the runtime path 404s do we auto-detect via the repo
        tree (monorepos = +1 tree call). An explicit ``repo_root`` override skips the
        probe entirely and prefixes deterministically. #190's
        ``candidate_file_not_in_repo`` stays the terminal when nothing resolves.
        Returns ``(resolved_path, RepoFile)``.
        """
        if explicit_prefix:
            resolved = resolve_repo_path(
                adapter=adapter,
                repo=target_repo,
                ref=ref,
                runtime_path=candidate_path,
                explicit_prefix=explicit_prefix,
            )
            return resolved, self._get_file_or_precondition(adapter, target_repo, resolved, ref)

        try:
            return candidate_path, adapter.get_file(target_repo, candidate_path, ref=ref)
        except VcsApiError as exc:
            if exc.status_code != 404:
                raise
            # Runtime path isn't at the repo root — auto-detect via the tree. A
            # RepoPathResolutionError (no match / ambiguous) becomes the typed
            # precondition; a genuine tree-read API failure still propagates.
            try:
                resolved = resolve_repo_path(adapter=adapter, repo=target_repo, ref=ref, runtime_path=candidate_path)
            except RepoPathResolutionError as res_exc:
                raise DraftPrPreconditionError(res_exc.reason, str(res_exc)) from res_exc
            return resolved, self._get_file_or_precondition(adapter, target_repo, resolved, ref)

    @staticmethod
    def _get_file_or_precondition(adapter, target_repo, path, ref):
        """Fetch ``path``; a 404 on the RESOLVED path is a terminal
        ``candidate_file_not_in_repo`` (compose with #190), other errors propagate."""
        try:
            return adapter.get_file(target_repo, path, ref=ref)
        except VcsApiError as exc:
            if exc.status_code == 404:
                raise DraftPrPreconditionError(
                    "candidate_file_not_in_repo",
                    f"The file '{path}' does not exist in {target_repo} (branch {ref}). This "
                    "finding may reference a different codebase than the allowlisted repo — "
                    "nothing to patch.",
                ) from exc
            raise

    def _notify_draft_pr_opened(self, *, workspace_id, task, performed_by, pr_url, repo) -> None:
        """HITL alert: a draft PR now awaits human review — tell the owner.

        Goes through the notification dispatcher funnel (reuses
        ``create_notification`` semantics: preference gating, dedup, deep
        link, realtime + web-push/email fan-out). Loss-tolerant — the PR
        itself must never be lost to a notification hiccup. The workspace
        owner id is resolved through the injected resolver (provider-owned
        ORM), so this use case holds no persistence import.
        """
        try:
            from components.notifications.workers.tasks import dispatch_notification_async
            from components.shared_kernel.application.transactional import on_commit

            owner_id = self._resolve_workspace_owner_id_fn()(str(workspace_id))
            if owner_id is None:
                return

            kwargs = {
                "recipient_id": str(owner_id),
                "actor_id": str(performed_by),
                "verb": f"opened a draft PR for review: {task.title[:180]}",
                "notification_type": "ai_event",
                "workspace_id": str(workspace_id),
                "target_ref": ["project", "task", str(task.id)],
                "allow_self_notify": True,
                "metadata": {
                    "kind": "soc.draft_pr_opened",
                    "task_id": str(task.id),
                    "pr_url": pr_url,
                    "repo": repo,
                },
            }
            on_commit(lambda: dispatch_notification_async.apply_async(kwargs=kwargs))
        except Exception:
            logger.exception(
                "draft_pr_notification_enqueue_failed task_id=%s workspace_id=%s",
                getattr(task, "id", None),
                workspace_id,
            )

    # ── Preconditions ─────────────────────────────────────────────────

    def _require_connection(self, workspace_id: str):
        # ADR 0010 Phase 2: resolves the provider-agnostic VcsConnection (seeded from any
        # legacy GitHubConnection by migration 0008) through the injected resolver — the
        # provider owns the ORM read (most-recent connection wins). A per-repo/provider
        # resolution refinement lands with the CRUD API (Phase 3).
        connection = self._resolve_connection_fn()(str(workspace_id))
        if connection is None:
            raise DraftPrPreconditionError(
                "no_github_connection",
                "No VCS connection is linked for this workspace.",
            )
        status = getattr(connection, "status", "")
        if status != _STATUS_CONNECTED:
            raise DraftPrPreconditionError(
                "connection_not_connected",
                f"The VCS connection is '{status}', not connected.",
            )
        return connection

    @staticmethod
    def _require_allowlisted_repo(connection, repo: str | None) -> str:
        allowlist = [r for r in (connection.repo_allowlist or []) if isinstance(r, str) and r.strip()]
        if not allowlist:
            raise DraftPrPreconditionError(
                "repo_not_allowlisted",
                "The GitHub connection has an empty repo allowlist — nothing to open PRs against.",
            )
        target = (repo or "").strip() or allowlist[0]
        if target not in allowlist:
            raise DraftPrPreconditionError(
                "repo_not_allowlisted",
                f"Repo '{target}' is not on the connection's allowlist.",
            )
        return target

    def _require_actionable_finding(self, workspace_id: str, task_id: str) -> ActionableFinding:
        # C3: the board Task belongs to ``project``; read it read-only through the
        # finding-facts port (never ``project``'s ORM). The adapter applies the
        # ``ai.log_watch`` source-type gate + workspace scope; a bad/absent id → None.
        finding = self._finding_facts_port().get_actionable_finding(workspace_id=workspace_id, task_id=task_id)
        if finding is None:
            raise DraftPrPreconditionError(
                "finding_not_found",
                f"No {_LOG_WATCH_SOURCE} finding {task_id} on this workspace's board.",
            )
        meta = finding.metadata or {}
        triage = meta.get("triage") or {}
        payload = meta.get("payload") or {}
        if triage.get("status") != "triaged":
            raise DraftPrPreconditionError(
                "finding_not_triaged",
                "The finding has not been triaged yet — triage it before opening a PR.",
            )
        if triage.get("needs_human") or payload.get("needs_human"):
            raise DraftPrPreconditionError(
                "finding_needs_human",
                "The finding's suggestion is flagged needs_human (ungrounded) — a human must "
                "resolve it; it never becomes an automatic PR.",
            )
        return finding

    def _require_capability(self, workspace_id: str) -> None:
        # #216: the triage agent's capability map belongs to the ``agents`` context —
        # read it through AgentCapabilityPort (never ``ai.agents``'s ORM). The port's
        # ``get_triage_capabilities`` resolves the same most-recent ``triage_agent`` row.
        capabilities = self._capability_port_().get_triage_capabilities(workspace_id=str(workspace_id))
        enabled = capabilities.get("open_draft_pr") is True if isinstance(capabilities, dict) else False
        if not enabled:
            raise DraftPrPreconditionError(
                "capability_disabled",
                "The triage agent's open_draft_pr capability is not enabled for this workspace.",
            )

    def _decrypt_token(self, connection) -> str:
        # The ciphertext lives on the resolver-provided connection object; the injected
        # secret-envelope callable turns it into the runtime token. The token is a
        # credential the use case must USE to call the host — it is never returned across
        # a port (no port method exposes it; #213's status seam stays presence-only).
        token = self._decrypt_fn()(getattr(connection, "token_ciphertext", "") or "")
        if not token:
            raise DraftPrPreconditionError(
                "no_github_token",
                "The GitHub connection has no stored token.",
            )
        return token

    def _resolve_commit_author(self, connection, performed_by: str) -> dict | None:
        """Resolve the commit author/committer identity from the connection's
        ``commit_identity`` policy. Returns ``{"name", "email"}`` or ``None`` (→ the
        adapter omits author/committer, so the host attributes the commit to the PAT
        owner — the default).

        - ``pat_owner`` (default) → ``None``.
        - ``operator`` → the approving user's name + email, read through the injected
          identity resolver. If the user or their email is missing, fall back to
          ``None`` — attribution never fails the PR.
        - ``custom`` → the stored ``commit_author_name`` / ``commit_author_email``
          (both required; the DTO validates that on write, so a half-set row falls
          back to ``None`` rather than sending a malformed identity).
        """
        mode = getattr(connection, "commit_identity", "") or ""

        if mode == _COMMIT_IDENTITY_OPERATOR:
            identity = self._resolve_operator_identity_fn()(str(performed_by))
            if not identity:
                return None
            name = (identity.get("name") or "").strip()
            email = (identity.get("email") or "").strip()
            if not email:
                return None
            return {"name": name or email, "email": email}

        if mode == _COMMIT_IDENTITY_CUSTOM:
            name = (getattr(connection, "commit_author_name", "") or "").strip()
            email = (getattr(connection, "commit_author_email", "") or "").strip()
            if name and email:
                return {"name": name, "email": email}
            return None

        return None

    # ── Output ────────────────────────────────────────────────────────

    @staticmethod
    def _build_pr_body(task, payload: dict, proposal) -> str:
        evidence_lines = []
        for ev in payload.get("evidence") or []:
            if isinstance(ev, dict):
                evidence_lines.append(f"- **{ev.get('type') or 'evidence'}**: `{(ev.get('detail') or '')[:300]}`")
        evidence = "\n".join(evidence_lines) or "- (none recorded)"
        return (
            f"## Finding\n{task.title}\n\n"
            f"**Service:** {payload.get('service') or 'unknown'} · "
            f"**Level:** {payload.get('level') or 'ERROR'} · "
            f"**Severity:** {payload.get('severity') or 'unknown'}\n\n"
            f"## Evidence\n{evidence}\n\n"
            f"## Probable cause\n{payload.get('probable_cause') or '(not determined)'}\n\n"
            f"## Suggested fix\n{payload.get('suggested_fix') or '(see change)'}\n\n"
            f"## Change\n{proposal.change_summary or 'Minimal fix for the error above.'}\n\n"
            f"---\nProvenance: Auto-Sec finding `{task.id}` — patch approved by a workspace operator. "
            f"This is a DRAFT; review and merge remain human decisions.\n"
        )
