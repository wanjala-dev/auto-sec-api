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
  2. **Soft-delete the corpus row FIRST** (``store.revoke`` → ``is_deleted=True``).
     This must precede the embedding delete: the embed task loads entries through
     the ``.active`` store, so once the row is soft-deleted a racing/scheduled
     re-embed can no longer resurrect the chunk. (Doing it after the embedding
     delete would leave a window where a re-embed re-adds what we just removed.)
  3. **Delete the embedding** from ``ai_embedding_chunks`` via the knowledge
     ``CorpusChunkIndexPort`` (keyed on ``remediation_entry:<id>``). This is the
     step that makes the entry unretrievable — retrieval reads the vector store, not
     the corpus row — so it MUST succeed; a failure here RAISES so the revocation is
     retried until the chunk is gone (the soft-delete already blocks re-embed, so a
     retry is safe and monotonic toward "gone").
  4. **Audit** the governance action (best-effort; never fails the revocation).

Result: a revoked entry is invisible to retrieval immediately (chunk deleted) and
permanently (row soft-deleted ⇒ never re-embedded, ⇒ never in ``list_for_workspace``).
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

        # (3) Delete the embedding — the step that removes it from RETRIEVAL. Must
        # succeed; a failure raises so the whole revocation is retried (safe: the row
        # is already soft-deleted, so no re-embed can race us).
        removed = self._corpus_index.delete_by_key(document_key=document_key_for(str(command.entry_id)))
        logger.info(
            "remediation_revoke_embedding_deleted entry_id=%s workspace_id=%s chunks=%s",
            command.entry_id,
            workspace_id,
            removed,
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
