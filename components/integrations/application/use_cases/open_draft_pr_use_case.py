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
from components.integrations.application.ports.vcs_port import VcsApiError, VcsPort

logger = logging.getLogger(__name__)

_LOG_WATCH_SOURCE = "ai.log_watch"
_ACTING_AGENT = "triage_agent"


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
    ) -> None:
        self._adapter_factory = adapter_factory
        self._advisor = advisor or LogPatchAdvisor()
        # Cross-context board access goes through ports (C2/C3). Defaults are
        # resolved lazily from the provider so the application layer holds no
        # direct infrastructure import (Rule 2); the provider is the composition
        # root that wires the concrete adapters.
        self._finding_facts = finding_facts
        self._pr_recorder = pr_recorder

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

        adapter = self._adapter_factory(connection.provider, token)
        default_branch = adapter.get_default_branch(target_repo)
        resolved_path, repo_file = self._resolve_and_fetch(
            adapter=adapter,
            target_repo=target_repo,
            ref=default_branch.name,
            candidate_path=candidate_path,
            explicit_prefix=(getattr(connection, "repo_root", "") or "").strip(),
        )

        proposal = self._advisor.propose(payload=payload, path=resolved_path, current_content=repo_file.content)
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

    @staticmethod
    def _notify_draft_pr_opened(*, workspace_id, task, performed_by, pr_url, repo) -> None:
        """HITL alert: a draft PR now awaits human review — tell the owner.

        Goes through the notification dispatcher funnel (reuses
        ``create_notification`` semantics: preference gating, dedup, deep
        link, realtime + web-push/email fan-out). Loss-tolerant — the PR
        itself must never be lost to a notification hiccup.
        """
        try:
            from components.notifications.workers.tasks import dispatch_notification_async
            from components.shared_kernel.application.transactional import on_commit
            from infrastructure.persistence.workspaces.models import Workspace

            owner_id = Workspace.objects.filter(id=workspace_id).values_list("workspace_owner_id", flat=True).first()
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

    @staticmethod
    def _require_connection(workspace_id: str):
        # ADR 0010 Phase 2: reads the provider-agnostic VcsConnection (seeded from any
        # legacy GitHubConnection by migration 0008). Most-recent connection wins; a
        # per-repo/provider resolution refinement lands with the CRUD API (Phase 3).
        from infrastructure.persistence.integrations.models import VcsConnection

        connection = VcsConnection.objects.filter(workspace_id=workspace_id).order_by("-created_at").first()
        if connection is None:
            raise DraftPrPreconditionError(
                "no_github_connection",
                "No VCS connection is linked for this workspace.",
            )
        if connection.status != VcsConnection.Status.CONNECTED:
            raise DraftPrPreconditionError(
                "connection_not_connected",
                f"The VCS connection is '{connection.status}', not connected.",
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

    @staticmethod
    def _require_capability(workspace_id: str) -> None:
        from infrastructure.persistence.ai.agents.models import Agent

        agent_row = (
            Agent.objects.filter(workspace_id=workspace_id, agent_type=_ACTING_AGENT).order_by("-created_at").first()
        )
        capabilities = ((agent_row.config or {}).get("capabilities") or {}) if agent_row else {}
        enabled = capabilities.get("open_draft_pr") is True if isinstance(capabilities, dict) else False
        if not enabled:
            raise DraftPrPreconditionError(
                "capability_disabled",
                "The triage agent's open_draft_pr capability is not enabled for this workspace.",
            )

    @staticmethod
    def _decrypt_token(connection) -> str:
        from components.integrations.application.providers.secret_envelope_provider import decrypt_secret

        token = decrypt_secret(connection.token_ciphertext)
        if not token:
            raise DraftPrPreconditionError(
                "no_github_token",
                "The GitHub connection has no stored token.",
            )
        return token

    @staticmethod
    def _resolve_commit_author(connection, performed_by: str) -> dict | None:
        """Resolve the commit author/committer identity from the connection's
        ``commit_identity`` policy. Returns ``{"name", "email"}`` or ``None`` (→ the
        adapter omits author/committer, so the host attributes the commit to the PAT
        owner — the default).

        - ``pat_owner`` (default) → ``None``.
        - ``operator`` → the approving user's name + email. If the user or their email
          is missing, fall back to ``None`` — attribution never fails the PR.
        - ``custom`` → the stored ``commit_author_name`` / ``commit_author_email``
          (both required; the DTO validates that on write, so a half-set row falls
          back to ``None`` rather than sending a malformed identity).
        """
        from infrastructure.persistence.integrations.models import VcsConnection

        mode = getattr(connection, "commit_identity", VcsConnection.CommitIdentity.PAT_OWNER)

        if mode == VcsConnection.CommitIdentity.OPERATOR:
            from infrastructure.persistence.users.models import CustomUser

            user = CustomUser.objects.filter(id=performed_by).first()
            email = (getattr(user, "email", "") or "").strip() if user else ""
            if not user or not email:
                return None
            name = (user.get_full_name() or "").strip() or (user.username or "").strip() or email
            return {"name": name, "email": email}

        if mode == VcsConnection.CommitIdentity.CUSTOM:
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
