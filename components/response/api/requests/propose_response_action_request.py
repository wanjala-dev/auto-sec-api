"""Input DTO for the operator-initiated propose endpoint.

Parses + validates the target of a security-group ingress revoke into a domain
``ResponseActionSpec``. The agent-driven proposal (a follow-up slice) builds the
same spec from a finding's structured remediation target; this endpoint lets an
operator (or a test / the demo) drive the whole reversible flow without the agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule


class ProposeRequestError(ValueError):
    """A malformed propose request (missing/invalid field)."""


@dataclass(frozen=True)
class ProposeResponseActionRequest:
    finding_fingerprint: str
    spec: ResponseActionSpec
    dry_run: bool

    @classmethod
    def from_request(cls, data: dict, *, default_dry_run: bool) -> ProposeResponseActionRequest:
        def _require(key: str) -> str:
            value = data.get(key)
            if value is None or str(value).strip() == "":
                raise ProposeRequestError(f"{key} is required")
            return str(value).strip()

        protocol = _require("protocol")
        from_port = data.get("from_port")
        to_port = data.get("to_port")
        try:
            rule = SecurityGroupRule(
                protocol=protocol,
                from_port=int(from_port) if from_port is not None else None,
                to_port=int(to_port) if to_port is not None else None,
                cidr=_require("cidr"),
                description=str(data.get("description") or ""),
            )
            spec = ResponseActionSpec(
                kind=ResponseActionKind.REVOKE_SG_INGRESS,
                account_id=_require("account_id"),
                region=_require("region"),
                group_id=_require("group_id"),
                rule=rule,
            )
        except (ValueError, TypeError) as exc:
            raise ProposeRequestError(str(exc)) from exc

        dry_run = data.get("dry_run")
        return cls(
            finding_fingerprint=_require("finding_fingerprint"),
            spec=spec,
            dry_run=default_dry_run if dry_run is None else bool(dry_run),
        )
