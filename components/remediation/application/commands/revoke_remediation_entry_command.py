"""Command DTO: revoke a remediation entry from the corpus (ADR 0012 P5).

A governance action, so it carries WHO is asking (``actor_user_id`` — checked for
owner/admin) and WHY (``reason`` — recorded in the audit trail). ``sign_off_*`` is
the alternative authorization path: a sign-off-approved revocation is authorised
even if the actor is not an owner/admin, so a reviewed governance decision can be
executed by the flow that carried it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RevokeRemediationEntryCommand:
    workspace_id: UUID
    entry_id: UUID
    # Governance identity + justification.
    actor_user_id: str | None = None
    reason: str = ""
    # Alternative authorization: a sign-off-approved revocation request.
    sign_off_artifact_type: str = ""
    sign_off_artifact_id: str = ""
