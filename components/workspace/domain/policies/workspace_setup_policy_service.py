from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceSetupSnapshot:
    workspace_id: object
    workspace_name: str
    # Security getting-started milestones (the funnel to first value).
    has_cloud_connected: bool
    has_first_scan: bool
    has_findings_triaged: bool
    has_teammates_invited: bool
    has_slack_connected: bool


@dataclass(frozen=True)
class SetupCheckDefinition:
    code: str
    label: str
    detail: str
    snapshot_field: str
    severity: str = "info"
    priority: int = 50
    dismissible: bool = True
    scope: str = "workspace"
    banner_title: str | None = None
    banner_message: str | None = None

    def is_complete(self, snapshot: WorkspaceSetupSnapshot) -> bool:
        return bool(getattr(snapshot, self.snapshot_field))

    def title(self) -> str:
        return self.banner_title or self.label

    def message(self) -> str:
        return self.banner_message or self.detail


@dataclass(frozen=True)
class SetupCheckResult:
    definition: SetupCheckDefinition
    is_complete: bool


class WorkspaceSetupPolicyService:
    def __init__(
        self,
        *,
        definitions: Sequence[SetupCheckDefinition] | None = None,
    ) -> None:
        self._definitions = tuple(definitions or self._default_definitions())

    @property
    def definitions(self) -> tuple[SetupCheckDefinition, ...]:
        return self._definitions

    def evaluate(self, snapshot: WorkspaceSetupSnapshot) -> list[SetupCheckResult]:
        return [
            SetupCheckResult(
                definition=definition,
                is_complete=definition.is_complete(snapshot),
            )
            for definition in self._definitions
        ]

    def build_status(self, snapshot: WorkspaceSetupSnapshot) -> dict:
        results = self.evaluate(snapshot)
        checks = []
        pending_codes = []
        recommendations = []

        for result in results:
            definition = result.definition
            checks.append(
                {
                    "code": definition.code,
                    "label": definition.label,
                    "is_complete": result.is_complete,
                    "detail": definition.detail,
                }
            )
            if result.is_complete:
                continue
            pending_codes.append(definition.code)
            recommendations.append(
                {
                    "code": definition.code,
                    "message": definition.detail,
                    "severity": definition.severity,
                    "scope": definition.scope,
                }
            )

        return {
            "workspace": snapshot.workspace_id,
            "workspace_name": snapshot.workspace_name,
            "is_complete": not pending_codes,
            "checks": checks,
            "pending": pending_codes,
            "recommendations": recommendations,
        }

    @staticmethod
    def _default_definitions() -> tuple[SetupCheckDefinition, ...]:
        # The security getting-started funnel: connect → scan → triage → invite →
        # notify. Ordered by priority (the path to first value first).
        return (
            SetupCheckDefinition(
                code="cloud_connected",
                label="Connect a cloud account",
                detail="Connect an AWS account so Auto-Sec can scan your cloud posture.",
                snapshot_field="has_cloud_connected",
                severity="warning",
                priority=10,
                banner_title="Connect your first cloud",
                banner_message="Connect an AWS account to start scanning your cloud for misconfigurations.",
            ),
            SetupCheckDefinition(
                code="first_scan",
                label="Run your first scan",
                detail="Run a scan to surface misconfigurations, exposures, and vulnerabilities.",
                snapshot_field="has_first_scan",
                severity="warning",
                priority=20,
                banner_title="Run your first scan",
                banner_message="Kick off a scan to see your findings, attack paths, and compliance posture.",
            ),
            SetupCheckDefinition(
                code="findings_triaged",
                label="Triage a finding",
                detail="Move a finding off the board — triage or resolve it — to close the loop.",
                snapshot_field="has_findings_triaged",
                severity="info",
                priority=30,
                banner_title="Triage your findings",
                banner_message="Review and triage a finding so your team knows what to act on.",
            ),
            SetupCheckDefinition(
                code="teammates_invited",
                label="Invite a teammate",
                detail="Invite a teammate so your Blue/Red teams can work findings together.",
                snapshot_field="has_teammates_invited",
                severity="info",
                priority=40,
                banner_title="Invite your team",
                banner_message="Invite teammates so you can triage and respond to findings together.",
            ),
            SetupCheckDefinition(
                code="slack_connected",
                label="Connect Slack",
                detail="Connect Slack so high-severity findings reach your team in real time.",
                snapshot_field="has_slack_connected",
                severity="info",
                priority=50,
                banner_title="Connect Slack",
                banner_message="Route critical findings to Slack so nothing slips through.",
            ),
        )
