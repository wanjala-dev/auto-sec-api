"""Resource DTOs: AWS connection + account link payloads for the REST adapter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AwsAccountLinkResource:
    account_id: str
    account_name: str
    status: str

    @classmethod
    def from_model(cls, link) -> AwsAccountLinkResource:
        return cls(
            account_id=link.account_id,
            account_name=link.account_name,
            status=link.status,
        )

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "status": self.status,
        }


@dataclass(frozen=True)
class AwsConnectionResource:
    """Serialized ``AwsOrganizationConnection`` (accounts capped at 200)."""

    id: str
    name: str
    management_account_id: str
    organization_id: str
    role_name: str
    external_id: str
    org_wide: bool
    regions: list
    trail_s3_bucket: str
    sqs_queue_url: str
    status: str
    last_verified_at: str | None
    last_error: str
    accounts: list = field(default_factory=list)

    @classmethod
    def from_model(cls, conn) -> AwsConnectionResource:
        return cls(
            id=str(conn.id),
            name=conn.name,
            management_account_id=conn.management_account_id,
            organization_id=conn.organization_id,
            role_name=conn.role_name,
            external_id=conn.external_id,
            org_wide=conn.org_wide,
            regions=conn.regions,
            trail_s3_bucket=conn.trail_s3_bucket,
            sqs_queue_url=conn.sqs_queue_url,
            status=conn.status,
            last_verified_at=(conn.last_verified_at.isoformat() if conn.last_verified_at else None),
            last_error=conn.last_error,
            accounts=[AwsAccountLinkResource.from_model(a) for a in conn.accounts.all()[:200]],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "management_account_id": self.management_account_id,
            "organization_id": self.organization_id,
            "role_name": self.role_name,
            "external_id": self.external_id,
            "org_wide": self.org_wide,
            "regions": self.regions,
            "trail_s3_bucket": self.trail_s3_bucket,
            "sqs_queue_url": self.sqs_queue_url,
            "status": self.status,
            "last_verified_at": self.last_verified_at,
            "last_error": self.last_error,
            "accounts": [a.to_dict() for a in self.accounts],
        }
