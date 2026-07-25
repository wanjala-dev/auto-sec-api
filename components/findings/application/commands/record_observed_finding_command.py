"""Command DTO for recording a scanner observation into the Finding SSOT."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.shared_kernel.domain.security import Severity


@dataclass(frozen=True)
class RecordObservedFindingCommand:
    workspace_id: UUID
    source: str
    fingerprint: str
    asset_urn: str
    severity: Severity
    title: str
    observed_at: datetime
    description: str = ""
    remediation: str = ""
    compliance: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RecordObservedFindingResult:
    finding_id: UUID
    is_new: bool
    changed: bool  # a raise-worthy change occurred (created / reopened / severity change)
