"""Backfill the stored patch onto LEGACY draft-PR records.

The open step persists the patch it commits (``path`` + a bounded unified diff +
the advisor's ``change_summary``) onto ``payload.draft_pr``, and the HUD renders
that inline on the finding and board-card callouts. Records opened BEFORE that
change carry only a ``url`` — so the HUD correctly degrades to a bare "VIEW DRAFT
PR" link, which is exactly the dead-end the inline review surface exists to kill.

This use case repairs those records, and only those:

* the integrations context owns VCS access, so it owns the *question* "what patch
  is in this PR?" — read through :meth:`VcsPort.get_pull_request_patch`, never a
  hand-rolled HTTP call;
* the board ``Task`` is ``project``'s data, so the write goes back through the
  SAME recorder port the open step writes through (C2) — same canonical metadata
  path, same ``bound_diff`` size bound, so a repaired record is indistinguishable
  from a freshly-opened one;
* the consent boundary is unchanged: the PR's repo must be on the resolving
  connection's allowlist, exactly as the merge-check read requires.

Honest by construction. A PR that is closed or merged still had a patch, so the
diff is stored *together with* its lifecycle state rather than dropped. A PR that
cannot be read (404, revoked token, repo de-allowlisted) or that returns no
reviewable patch is SKIPPED with a named reason and counted — never filled with
an invented or approximated diff. Re-running is safe: a record that already
carries a diff is skipped by the owning write.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from components.integrations.application.ports.finding_facts_port import FindingFactsPort
from components.integrations.application.ports.finding_pr_recorder_port import FindingPrRecorderPort
from components.integrations.application.ports.vcs_port import VcsApiError, VcsPort
from components.integrations.application.use_cases.check_pull_request_merged_use_case import parse_pr_url

logger = logging.getLogger(__name__)

#: Stamped onto the provenance event so the board says WHY the card changed.
BACKFILL_REASON = "legacy_patch_backfill"


@dataclass(frozen=True)
class BackfillOutcome:
    """What happened to ONE legacy record. ``filled`` false is a skip, not a failure."""

    workspace_id: str
    task_id: str
    pr_url: str
    repo: str
    filled: bool
    reason: str
    path: str = ""
    diff_chars: int = 0
    pr_state: str = ""
    merged: bool = False


@dataclass(frozen=True)
class BackfillReport:
    outcomes: tuple[BackfillOutcome, ...] = ()

    @property
    def filled(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.filled)

    @property
    def skipped(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.filled)


class BackfillDraftPrPatchesUseCase:
    def __init__(
        self,
        *,
        finding_facts: FindingFactsPort,
        pr_recorder: FindingPrRecorderPort,
        resolve_connection: Callable[[str], object | None],
        decrypt: Callable[[str], str],
        resolve_adapter: Callable[[str, str], VcsPort],
    ) -> None:
        self._finding_facts = finding_facts
        self._pr_recorder = pr_recorder
        self._resolve_connection = resolve_connection
        self._decrypt = decrypt
        self._resolve_adapter = resolve_adapter

    def execute(self, *, workspace_id: str = "", limit: int = 500, dry_run: bool = False) -> BackfillReport:
        gaps = self._finding_facts.list_draft_pr_patch_gaps(workspace_id=workspace_id, limit=limit)
        logger.info(
            "backfill_draft_pr_patches started workspace_id=%s candidates=%s dry_run=%s",
            workspace_id or "*",
            len(gaps),
            dry_run,
        )

        # One resolved adapter per workspace — the sweep is workspace-clustered and
        # a connection read + token decrypt per record would be pure waste.
        adapters: dict[str, VcsPort | None] = {}
        allowlists: dict[str, list[str]] = {}
        outcomes: list[BackfillOutcome] = []

        for gap in gaps:
            outcomes.append(self._backfill_one(gap, adapters=adapters, allowlists=allowlists, dry_run=dry_run))

        report = BackfillReport(outcomes=tuple(outcomes))
        logger.info(
            "backfill_draft_pr_patches finished workspace_id=%s filled=%s skipped=%s dry_run=%s",
            workspace_id or "*",
            report.filled,
            report.skipped,
            dry_run,
        )
        return report

    # ── one record ────────────────────────────────────────────────────

    def _backfill_one(self, gap, *, adapters: dict, allowlists: dict, dry_run: bool) -> BackfillOutcome:
        parsed = parse_pr_url(gap.pr_url)
        if parsed is None:
            return self._skip(gap, "unparseable_pr_url")
        # The URL is authoritative for WHERE the PR lives — the record's own
        # ``repo`` field is a label written beside it and could disagree.
        repo, number = parsed

        adapter = self._adapter_for(gap.workspace_id, adapters=adapters, allowlists=allowlists)
        if adapter is None:
            return self._skip(gap, "no_usable_vcs_connection", repo=repo)

        # Consent boundary — identical to the merge-check read: never touch a repo
        # the operator has not allowlisted on this connection.
        if repo not in allowlists.get(gap.workspace_id, []):
            return self._skip(gap, "repo_not_allowlisted", repo=repo)

        try:
            patch = adapter.get_pull_request_patch(repo, number)
            state = adapter.get_pull_request(repo, number)
        except VcsApiError as exc:
            logger.info(
                "backfill_draft_pr_patches host_read_failed workspace_id=%s task_id=%s repo=%s pr=%s status=%s",
                gap.workspace_id,
                gap.task_id,
                repo,
                number,
                exc.status_code,
            )
            return self._skip(gap, f"host_api_error_{exc.status_code or 'unknown'}", repo=repo)

        if not (patch.diff or "").strip():
            # The host has no reviewable patch (binary-only, or too large to inline).
            # Nothing honest to store — the link-only record stands.
            return self._skip(gap, "no_patch_returned", repo=repo)

        if patch.file_count > 1:
            # Auto-Sec's own draft PRs commit exactly one file; more means a human
            # pushed to the branch. Worth seeing, not worth refusing — the whole
            # patch is stored and the operator reviews what is actually there.
            logger.info(
                "backfill_draft_pr_patches multi_file_pr workspace_id=%s task_id=%s repo=%s pr=%s files=%s",
                gap.workspace_id,
                gap.task_id,
                repo,
                number,
                patch.file_count,
            )

        if dry_run:
            return BackfillOutcome(
                workspace_id=gap.workspace_id,
                task_id=gap.task_id,
                pr_url=gap.pr_url,
                repo=repo,
                filled=False,
                reason="dry_run",
                path=patch.path,
                diff_chars=len(patch.diff),
                pr_state=state.state,
                merged=state.merged,
            )

        attached, reason = self._pr_recorder.attach_draft_pr_patch(
            workspace_id=gap.workspace_id,
            task_id=gap.task_id,
            path=patch.path,
            diff=patch.diff,
            # Legacy records predate the advisor summary being persisted, and it is
            # not recoverable from the host. Left EMPTY rather than reconstructed —
            # the HUD renders the diff (what it gates on) and claims nothing extra.
            change_summary="",
            pr_state=state.state,
            merged=state.merged,
            reason=BACKFILL_REASON,
        )
        logger.info(
            "backfill_draft_pr_patches record workspace_id=%s task_id=%s repo=%s pr=%s "
            "filled=%s reason=%s diff_chars=%s pr_state=%s merged=%s",
            gap.workspace_id,
            gap.task_id,
            repo,
            number,
            attached,
            reason,
            len(patch.diff),
            state.state,
            state.merged,
        )
        return BackfillOutcome(
            workspace_id=gap.workspace_id,
            task_id=gap.task_id,
            pr_url=gap.pr_url,
            repo=repo,
            filled=attached,
            reason=reason,
            path=patch.path,
            diff_chars=len(patch.diff),
            pr_state=state.state,
            merged=state.merged,
        )

    # ── helpers ───────────────────────────────────────────────────────

    def _adapter_for(self, workspace_id: str, *, adapters: dict, allowlists: dict) -> VcsPort | None:
        """Resolve (and memoise) the workspace's VCS adapter + repo allowlist."""
        if workspace_id in adapters:
            return adapters[workspace_id]

        adapter: VcsPort | None = None
        connection = self._resolve_connection(workspace_id)
        if connection is None:
            logger.info("backfill_draft_pr_patches no_connection workspace_id=%s", workspace_id)
        else:
            token = self._decrypt(getattr(connection, "token_ciphertext", "") or "")
            if not token:
                logger.info("backfill_draft_pr_patches no_token workspace_id=%s", workspace_id)
            else:
                try:
                    adapter = self._resolve_adapter(getattr(connection, "provider", ""), token)
                except Exception:
                    # An unsupported/unbuildable provider is a skip for this whole
                    # workspace, logged with the workspace id only — never the token.
                    logger.exception("backfill_draft_pr_patches adapter_unavailable workspace_id=%s", workspace_id)
                    adapter = None
            allowlists[workspace_id] = [
                r.strip()
                for r in (getattr(connection, "repo_allowlist", None) or [])
                if isinstance(r, str) and r.strip()
            ]

        adapters[workspace_id] = adapter
        allowlists.setdefault(workspace_id, [])
        return adapter

    @staticmethod
    def _skip(gap, reason: str, *, repo: str = "") -> BackfillOutcome:
        return BackfillOutcome(
            workspace_id=gap.workspace_id,
            task_id=gap.task_id,
            pr_url=gap.pr_url,
            repo=repo or gap.repo,
            filled=False,
            reason=reason,
        )
