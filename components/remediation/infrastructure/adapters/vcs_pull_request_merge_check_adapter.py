"""Adapter: verify a draft PR's merge via the ``integrations`` VcsPort (ADR 0012 P4a).

Implements :class:`PullRequestMergeCheckPort`. Loads the workspace's most-recent
CONNECTED ``VcsConnection``, decrypts its token through the integrations secret
envelope, resolves the matching adapter from the VCS provider registry, and reads
the PR's current state. The response's ``merged`` boolean is the un-forgeable
"the fix was applied" fact P3 lacked.

Cross-context discipline (architecture skill C3): remediation calls only the
``integrations`` *application* surface — the ``VcsPort`` type, the provider
registry (a composition root), and the secret-envelope provider. It does not
import integrations infrastructure. Reading the ``VcsConnection`` ORM row is a
persistence read (same sanctioned pattern as ``BoardFindingFactsRepository``
reading ``project.Task``), not a components.integrations.infrastructure import.

Fail-closed: no connection, a decrypt miss, an unsupported provider, or any VCS
API error resolves to ``checked=False`` — the reconciler then leaves the finding
for the next cycle. It never assumes "merged" on an error.
"""

from __future__ import annotations

import logging

from components.remediation.application.ports.pull_request_merge_check_port import (
    MergeStatus,
    PullRequestMergeCheckPort,
)

logger = logging.getLogger(__name__)


class VcsPullRequestMergeCheckAdapter(PullRequestMergeCheckPort):
    def check_merged(self, *, workspace_id: str, repo: str, pr_ref: str) -> MergeStatus:
        from components.integrations.application.ports.vcs_port import VcsApiError
        from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
        from components.integrations.application.providers.vcs_provider import (
            UnsupportedVcsProviderError,
            get_vcs_adapter,
        )
        from infrastructure.persistence.integrations.models import VcsConnection

        if not repo or not pr_ref:
            return MergeStatus(checked=False, merged=False, detail="missing repo or pr_ref")

        connection = (
            VcsConnection.objects.filter(workspace_id=workspace_id, status=VcsConnection.Status.CONNECTED)
            .order_by("-created_at")
            .first()
        )
        if connection is None:
            return MergeStatus(checked=False, merged=False, detail="no connected VCS connection")

        token = decrypt_secret(connection.token_ciphertext)
        if not token:
            return MergeStatus(checked=False, merged=False, detail="no stored VCS token")

        try:
            adapter = get_vcs_adapter(connection.provider, token)
            state = adapter.get_pull_request(repo, pr_ref)
        except UnsupportedVcsProviderError:
            logger.warning(
                "remediation_merge_check_unsupported_provider workspace_id=%s provider=%s",
                workspace_id,
                connection.provider,
            )
            return MergeStatus(checked=False, merged=False, detail="unsupported VCS provider")
        except VcsApiError:
            # A read failure (404, transient, un-parseable ref) is NOT "not merged";
            # it is "could not verify". Skip this finding this cycle — never guess.
            logger.exception(
                "remediation_merge_check_api_error workspace_id=%s repo=%s",
                workspace_id,
                repo,
            )
            return MergeStatus(checked=False, merged=False, detail="VCS API error")

        # ``pr_ref`` is the stored draft-PR URL — echo it back as the canonical link.
        return MergeStatus(
            checked=True,
            merged=bool(state.merged),
            pr_url=pr_ref,
            detail=f"state={state.state}",
        )
