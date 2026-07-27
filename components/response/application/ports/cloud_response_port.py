"""Port: perform (and pre-flight) a reversible cloud mutation.

Shaped to the core's need, not to boto3: the application asks "apply this spec"
and "does this public rule actually exist on that group right now?" — the adapter
maps those onto EC2 ``revoke``/``authorize_security_group_ingress`` and
``describe_security_group_rules``. ``dry_run`` threads through to AWS's native
DryRun probe so a proposal can be validated without changing anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.response_outcome import ResponseOutcome
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule


class CloudResponsePort(ABC):
    @abstractmethod
    def apply(self, spec: ResponseActionSpec, *, workspace_id: str, dry_run: bool) -> ResponseOutcome:
        """Execute the spec's mutation (revoke or authorize) in ``workspace_id``'s
        account. With ``dry_run``, only probe permissions — no state changes."""

    @abstractmethod
    def find_matching_public_ingress(
        self,
        *,
        workspace_id: str,
        account_id: str,
        region: str,
        group_id: str,
        rule: SecurityGroupRule,
    ) -> SecurityGroupRule | None:
        """Return the live ingress rule on the group that matches ``rule`` (same
        protocol/ports/CIDR) if — and only if — it currently exists and is
        public. ``None`` means there is nothing to revoke (already fixed, or the
        proposal is ungrounded). Read-only; used to ground a proposal against
        the real security group before a human is ever asked to approve it.
        """
