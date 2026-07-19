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
silent. GitHub API failures propagate as ``GitHubApiError``.

Rung 1 (HITL): ``performed_by`` is the approving human's user id; the tool's
``irreversible`` risk tier denies autonomous runs before this code is reached.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from components.integrations.application.log_patch_advisor_service import (
    LogPatchAdvisor,
    derive_candidate_path,
)
from components.integrations.application.ports.github_pr_port import GitHubPrPort

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
        adapter_factory: Callable[[str], GitHubPrPort],
        advisor: LogPatchAdvisor | None = None,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._advisor = advisor or LogPatchAdvisor()

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

        adapter = self._adapter_factory(token)
        default_branch = adapter.get_default_branch(target_repo)
        repo_file = adapter.get_file(target_repo, candidate_path, ref=default_branch.name)

        proposal = self._advisor.propose(payload=payload, path=candidate_path, current_content=repo_file.content)
        if proposal is None:
            raise DraftPrPreconditionError(
                "no_grounded_patch",
                "No grounded patch could be generated from the finding's evidence.",
            )

        branch = f"autosec/finding-{task_id}"
        title = f"[Auto-Sec] {task.title[:180]}"
        adapter.create_branch(target_repo, branch, from_sha=default_branch.head_sha)
        adapter.commit_file(
            target_repo,
            branch,
            proposal.path,
            proposal.updated_content,
            message=title,
            file_sha=repo_file.sha,
        )
        pr = adapter.open_draft_pr(
            target_repo,
            head=branch,
            base=default_branch.name,
            title=title,
            body=self._build_pr_body(task, payload, proposal),
        )

        self._record_on_finding(task_id, workspace_id, pr, branch, performed_by)
        logger.info(
            "open_draft_pr opened task_id=%s workspace_id=%s repo=%s pr=%s performed_by=%s",
            task_id,
            workspace_id,
            target_repo,
            pr.url,
            performed_by,
        )
        return DraftPrResult(url=pr.url, repo=target_repo, branch=branch, created=True)

    # ── Preconditions ─────────────────────────────────────────────────

    @staticmethod
    def _require_connection(workspace_id: str):
        from infrastructure.persistence.integrations.models import GitHubConnection

        connection = GitHubConnection.objects.filter(workspace_id=workspace_id).order_by("-created_at").first()
        if connection is None:
            raise DraftPrPreconditionError(
                "no_github_connection",
                "No GitHub connection is installed for this workspace.",
            )
        if connection.status != GitHubConnection.Status.CONNECTED:
            raise DraftPrPreconditionError(
                "connection_not_connected",
                f"The GitHub connection is '{connection.status}', not connected.",
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

    @staticmethod
    def _require_actionable_finding(workspace_id: str, task_id: str):
        from infrastructure.persistence.project.models import Task

        task = Task.objects.filter(id=task_id, workspace_id=workspace_id, source_type=_LOG_WATCH_SOURCE).first()
        if task is None:
            raise DraftPrPreconditionError(
                "finding_not_found",
                f"No {_LOG_WATCH_SOURCE} finding {task_id} on this workspace's board.",
            )
        meta = task.metadata or {}
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
        return task

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

    @staticmethod
    def _record_on_finding(task_id: str, workspace_id: str, pr, branch: str, performed_by: str) -> None:
        """Write the PR link + provenance + a card comment onto the finding.

        Re-checks ``draft_pr`` right before writing so a concurrent open (two
        operators clicking at once) keeps the first PR's record.
        """
        from infrastructure.persistence.project.models import Task, TaskComment
        from infrastructure.persistence.users.models import CustomUser

        task = Task.objects.filter(id=task_id, workspace_id=workspace_id).first()
        if task is None:  # deleted between the precondition check and now
            return
        meta = task.metadata or {}
        payload = meta.get("payload") or {}
        if (payload.get("draft_pr") or {}).get("url"):
            return

        opened_at = datetime.now(UTC).isoformat()
        payload["draft_pr"] = {
            "url": pr.url,
            "repo": pr.repo,
            "branch": branch,
            "opened_by": str(performed_by),
            "opened_at": opened_at,
        }
        meta["payload"] = payload

        # Same growable provenance shape the detector/triage pipeline appends to.
        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": f"agent:{_ACTING_AGENT} via user:{performed_by}",
                "action": f"opened draft PR {pr.url}",
                "at": opened_at,
            }
        )
        provenance["last_handled_by"] = _ACTING_AGENT
        provenance["last_handled_at"] = opened_at
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])

        author = CustomUser.objects.filter(id=performed_by).first()
        if author is not None:
            TaskComment.objects.create(
                task=task,
                author=author,
                comment=(f"🔧 Draft PR opened for this finding: {pr.url} (branch `{branch}`, repo `{pr.repo}`)."),
            )
