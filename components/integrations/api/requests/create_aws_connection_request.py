"""Request DTO: create an AWS organization connection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreateAwsConnectionRequest:
    """Validated input for ``POST /integrations/workspaces/<ws>/aws/``."""

    management_account_id: str
    name: str = ""
    role_name: str = ""
    org_wide: bool = True
    regions: list = field(default_factory=list)
    trail_s3_bucket: str = ""
    sqs_queue_url: str = ""

    @classmethod
    def from_payload(cls, data: dict) -> CreateAwsConnectionRequest:
        data = data or {}
        return cls(
            management_account_id=str(data.get("management_account_id") or "").strip(),
            name=str(data.get("name") or ""),
            role_name=str(data.get("role_name") or ""),
            org_wide=bool(data.get("org_wide", True)),
            regions=list(data.get("regions") or []),
            trail_s3_bucket=str(data.get("trail_s3_bucket") or ""),
            sqs_queue_url=str(data.get("sqs_queue_url") or ""),
        )

    def validation_error(self) -> str | None:
        if not (self.management_account_id.isdigit() and len(self.management_account_id) == 12):
            return "management_account_id must be a 12-digit AWS account id."
        return None
