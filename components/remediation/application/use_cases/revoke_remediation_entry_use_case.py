"""RevokeRemediationEntryUseCase — governance-gated corpus revocation (ADR 0012 P5).

Pulls a vetted fix out of the retrievable corpus so triage can NEVER surface it
again. This is the D1-residual lever the ADR names: a fix that was legitimately
approved but later found insecure (or whose finding reopened) must be removable —
and because removal is itself security-sensitive (an attacker who could revoke
freely could strip a workspace of its proven fixes, or hide a bad one), it is
**gated + audited**.

The flow, in order (the ordering is load-bearing):

  1. **Authorize.** Owner/admin (``RemediationGovernancePort``) OR a sign-off-approved
     request (``SignOffGatePort``). Neither ⇒ ``RevocationNotAuthorizedError`` and
     NOTHING is touched (fail-closed).
  2. **Soft-delete the corpus row** (``store.revoke`` → ``is_deleted=True``). This is
     the AUTHORITY on retrievability: retrieval cross-checks every candidate chunk
     against the ``.active`` store and drops any whose entry is not active (see
     ``PgVectorRemediationRetrievalAdapter._drop_revoked``), so the moment this
     commits the entry is unretrievable — regardless of the embedding's fate. It
     also blocks any scheduled re-embed (the embed task loads via ``.active``).
  3. **Delete the embedding** from ``ai_embedding_chunks`` via the knowledge
     ``CorpusChunkIndexPort`` — **best-effort cleanup**, NOT the security control.
     Because retrieval no longer depends on it, a failure here is logged loud +
     alertable but does NOT fail the revocation (the entry is already unretrievable).
  4. **Audit** the governance action (best-effort; never fails the revocation).

Result: a revoked entry is invisible to retrieval immediately AND permanently — the
soft-delete + active-status cross-check guarantee it even if the embedding-delete
fails; the chunk-delete is housekeeping that a retry / re-embed-refusal completes.
"""

from __future__ import annotations

import logging

from components.knowledge.application.ports.corpus_chunk_index_port import (
    CorpusChunkIndexPort,
)
from components.remediation.application.commands.revoke_remediation_entry_command import (
    RevokeRemediationEntryCommand,
)
from components.remediation.application.ports.remediation_audit_port import (
    RemediationAuditPort,
)
from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.application.ports.remediation_governance_port import (
    RemediationGovernancePort,
)
from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
    document_key_for,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.domain.errors import RevocationNotAuthorizedError

logger = logging.getLogger(__name__)


class RevokeRemediationEntryUseCase:
    def __init__(
        self,
        *,
        store: RemediationEntryStorePort,
        corpus_index: CorpusChunkIndexPort,
        governance: RemediationGovernancePort,
        sign_off_gate: SignOffGatePort,
        audit: RemediationAuditPort,
    ) -> None:
        self._store = store
        self._corpus_index = corpus_index
        self._governance = governance
        self._sign_off_gate = sign_off_gate
        self._audit = audit

    def execute(self, command: RevokeRemediationEntryCommand) -> RemediationEntry | None:
        workspace_id = command.workspace_id

        # (1) Authorize — owner/admin OR sign-off-approved. Fail-closed.
        if not self._authorized(command):
            logger.warning(
                "remediation_revoke_unauthorized entry_id=%s workspace_id=%s actor_id=%s",
                command.entry_id,
                workspace_id,
                command.actor_user_id,
            )
            raise RevocationNotAuthorizedError(workspace_id=str(workspace_id), actor_id=command.actor_user_id)

        # (2) Soft-delete the corpus row FIRST (blocks any future re-embed).
        entry = self._store.revoke(
            entry_id=command.entry_id,
            workspace_id=workspace_id,
            revoked_by=str(command.actor_user_id or ""),
            reason=command.reason,
        )
        if entry is None:
            # Nothing to revoke in THIS workspace (absent / foreign id — D4). No-op.
            logger.info(
                "remediation_revoke_noop_absent entry_id=%s workspace_id=%s",
                command.entry_id,
                workspace_id,
            )
            return None

        # (3) Delete the embedding — best-effort cleanup. Retrievability is ALREADY
        # settled by the soft-delete above: retrieval cross-checks every candidate
        # against the ``.active`` store and drops revoked entries, so a stale chunk
        # can never be surfaced. Deleting the chunk is housekeeping (keeps the vector
        # store from growing), so a failure here is logged loud+alertable but does
        # NOT fail the revocation (the entry is already unretrievable) — a retry /
        # the eventual re-embed-refusal cleans it up.
        try:
            removed = self._corpus_index.delete_by_key(document_key=document_key_for(str(command.entry_id)))
            logger.info(
                "remediation_revoke_embedding_deleted entry_id=%s workspace_id=%s chunks=%s",
                command.entry_id,
                workspace_id,
                removed,
            )
        except Exception:
            logger.exception(
                "remediation_revoke_embedding_delete_failed entry_id=%s workspace_id=%s "
                "(entry already unretrievable via active-status check; chunk left for cleanup)",
                command.entry_id,
                workspace_id,
            )

        # (4) Audit the governance action (best-effort — never fails the revocation).
        self._audit.log_revocation(
            entry_id=command.entry_id,
            workspace_id=workspace_id,
            actor_id=command.actor_user_id,
            reason=command.reason,
        )
        logger.info(
            "remediation_entry_revoked entry_id=%s workspace_id=%s actor_id=%s",
            command.entry_id,
            workspace_id,
            command.actor_user_id,
        )
        return entry

    def _authorized(self, command: RevokeRemediationEntryCommand) -> bool:
        if self._governance.can_revoke(workspace_id=command.workspace_id, actor_user_id=command.actor_user_id):
            return True
        # Alternative path: a sign-off-approved revocation request.
        if command.sign_off_artifact_type and command.sign_off_artifact_id:
            return self._sign_off_gate.is_approved(
                artifact_type=command.sign_off_artifact_type,
                artifact_id=command.sign_off_artifact_id,
            )
        return False
