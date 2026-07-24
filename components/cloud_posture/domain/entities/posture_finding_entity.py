"""Immutable normalized posture finding — one parsed Prowler check result.

Framework-free; produced by the Prowler parser, persisted by the ingest service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from components.cloud_posture.domain.value_objects.enums import CheckStatus, Severity


@dataclass(frozen=True)
class NormalizedPostureFinding:
    check_id: str
    title: str
    severity: Severity
    status: CheckStatus
    account_id: str = ""
    region: str = ""
    service: str = ""
    resource_uid: str = ""
    resource_name: str = ""
    resource_type: str = ""
    finding_uid: str = ""
    description: str = ""
    remediation: str = ""
    compliance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.check_id:
            raise ValueError("NormalizedPostureFinding.check_id is required")
        object.__setattr__(self, "compliance", MappingProxyType(dict(self.compliance)))

    @property
    def is_actionable(self) -> bool:
        """FAIL / MANUAL checks are worth surfacing; PASS is not."""
        return self.status is not CheckStatus.PASS
