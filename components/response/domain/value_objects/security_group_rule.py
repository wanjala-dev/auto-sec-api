"""SecurityGroupRule — one inbound (ingress) rule, captured exactly.

The AWS API requires that a revoke match an existing rule's properties *exactly*
(protocol + port range + CIDR), and the inverse (re-authorize) must reconstruct
the *same* rule byte-for-byte or the rollback restores something subtly
different. So this value object is the single, precise description of the rule a
response action revokes and later re-authorizes — nothing lossy in between.
"""

from __future__ import annotations

from dataclasses import dataclass

# The wildcard CIDRs that make an ingress rule "public" (internet-facing). A
# response action only ever targets a rule whose CIDR is one of these — a
# non-public rule is not an exposure and must not be revoked.
PUBLIC_CIDRS = ("0.0.0.0/0", "::/0")


@dataclass(frozen=True)
class SecurityGroupRule:
    """An EC2 security-group ingress rule, precise enough to revoke and restore.

    ``protocol`` is the AWS ``IpProtocol`` token: ``tcp`` / ``udp`` / ``icmp`` /
    ``icmpv6`` / ``-1`` (all). For ``-1`` the port range is not meaningful and is
    normalised to ``None``.
    """

    protocol: str
    from_port: int | None
    to_port: int | None
    cidr: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.protocol:
            raise ValueError("SecurityGroupRule.protocol is required")
        if not self.cidr:
            raise ValueError("SecurityGroupRule.cidr is required")
        # "-1" (all protocols) has no port range; a real protocol with a port
        # must carry both ends so the revoke/authorize IpPermissions match.
        if self.protocol != "-1":
            if (self.from_port is None) != (self.to_port is None):
                raise ValueError("from_port and to_port must both be set or both be omitted")

    @property
    def is_ipv6(self) -> bool:
        return ":" in self.cidr

    @property
    def is_public(self) -> bool:
        return self.cidr in PUBLIC_CIDRS

    def to_ip_permissions(self) -> list[dict]:
        """Render as the boto3 ``IpPermissions`` list for revoke/authorize.

        Both ``revoke_security_group_ingress`` and
        ``authorize_security_group_ingress`` take the identical shape, so the
        forward action and its inverse serialise the same way.
        """
        entry: dict = {"IpProtocol": self.protocol}
        if self.from_port is not None:
            entry["FromPort"] = self.from_port
        if self.to_port is not None:
            entry["ToPort"] = self.to_port
        range_key = "Ipv6Ranges" if self.is_ipv6 else "IpRanges"
        cidr_key = "CidrIpv6" if self.is_ipv6 else "CidrIp"
        cidr_entry: dict = {cidr_key: self.cidr}
        if self.description:
            cidr_entry["Description"] = self.description
        entry[range_key] = [cidr_entry]
        return [entry]

    def human_label(self) -> str:
        if self.protocol == "-1":
            ports = "all traffic"
        elif self.from_port == self.to_port:
            ports = f"{self.protocol}/{self.from_port}"
        else:
            ports = f"{self.protocol}/{self.from_port}-{self.to_port}"
        return f"{ports} from {self.cidr}"

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "from_port": self.from_port,
            "to_port": self.to_port,
            "cidr": self.cidr,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SecurityGroupRule:
        return cls(
            protocol=str(data["protocol"]),
            from_port=data.get("from_port"),
            to_port=data.get("to_port"),
            cidr=str(data["cidr"]),
            description=str(data.get("description") or ""),
        )
