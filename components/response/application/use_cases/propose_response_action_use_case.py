"""Propose a reversible response action — record it, compute its undo, ground it.

Proposing has NO external effect: it writes a PROPOSED ledger row and returns.
That is why an autonomous agent is allowed to propose (a ``reversible_write``)
while only a human may approve the execution (the ``irreversible`` step). Before
a human is ever asked to decide, the proposal is grounded against the live
security group — the rule must actually exist and be public — so the queue never
fills with stale or hallucinated actions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from uuid import UUID

from components.response.application.ports.cloud_response_port import CloudResponsePort
from components.response.application.ports.response_action_store_port import (
    ResponseActionStorePort,
)
from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.errors import UnsafeActionError
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec

logger = logging.getLogger(__name__)


class ProposeResponseActionUseCase:
    def __init__(self, *, store: ResponseActionStorePort, cloud_port: CloudResponsePort) -> None:
        self._store = store
        self._cloud = cloud_port

    def execute(
        self,
        *,
        workspace_id: UUID,
        finding_fingerprint: str,
        spec: ResponseActionSpec,
        requested_by: str,
        dry_run: bool,
        validate_live: bool = True,
    ) -> ResponseActionExecution:
        if spec.kind != ResponseActionKind.REVOKE_SG_INGRESS:
            # authorize is only ever generated as the inverse of a revoke; it is
            # never a standalone proposal (we don't open ingress on a finding).
            raise UnsafeActionError(f"{spec.kind.value} is not a proposable response action")
        if not spec.rule.is_public:
            raise UnsafeActionError(
                f"rule {spec.rule.human_label()} is not public (CIDR is scoped) — not an exposure to revoke"
            )

        if validate_live:
            match = self._cloud.find_matching_public_ingress(
                workspace_id=str(workspace_id),
                account_id=spec.account_id,
                region=spec.region,
                group_id=spec.group_id,
                rule=spec.rule,
            )
            if match is None:
                raise UnsafeActionError(
                    f"no matching public ingress {spec.rule.human_label()} on {spec.group_id} — "
                    "nothing to revoke (already remediated, or the target is wrong)"
                )

        now = datetime.now(UTC)
        action = ResponseActionExecution(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            finding_fingerprint=finding_fingerprint,
            spec=spec,
            inverse_spec=spec.inverse(),
            status=ExecutionStatus.PROPOSED,
            dry_run=dry_run,
            requested_by=requested_by,
            requested_at=now,
        )
        saved = self._store.save(action)
        logger.info(
            "response_action_proposed id=%s workspace=%s fingerprint=%s dry_run=%s",
            saved.id,
            workspace_id,
            finding_fingerprint,
            dry_run,
        )
        return saved
