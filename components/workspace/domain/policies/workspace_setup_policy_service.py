from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class WorkspaceSetupSnapshot:
    workspace_id: object
    workspace_name: str
    has_contribution_means: bool
    has_story: bool
    has_cover_photo: bool
    has_budget: bool
    has_active_team: bool


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
        return (
            SetupCheckDefinition(
                code="has_contribution_means",
                label="Contribution means configured",
                detail="Add at least one contribution method so supporters know how to help.",
                snapshot_field="has_contribution_means",
                severity="info",
                priority=40,
                banner_title="Add contribution means",
                banner_message="Add at least one contribution method so supporters know how supporters can contribute.",
            ),
            SetupCheckDefinition(
                code="has_story",
                label="Workspace story authored",
                detail="Share your workspace story so visitors understand your mission.",
                snapshot_field="has_story",
                severity="info",
                priority=45,
                banner_title="Tell your story",
                banner_message="Write a compelling workspace story so visitors can connect with your mission.",
            ),
            SetupCheckDefinition(
                code="has_cover_photo",
                label="Cover photo added",
                detail="Upload a cover photo to make the workspace page more engaging.",
                snapshot_field="has_cover_photo",
                severity="info",
                priority=46,
                banner_title="Add a cover photo",
                banner_message="Upload a cover photo to make your workspace stand out.",
            ),
            SetupCheckDefinition(
                code="has_budget",
                label="Budget created",
                detail="Create a budget so supporters can see how resources are allocated.",
                snapshot_field="has_budget",
                severity="warning",
                priority=47,
                banner_title="Create a budget",
                banner_message="Set up a workspace budget so supporters can understand how funds will be used.",
            ),
            SetupCheckDefinition(
                code="has_active_team",
                label="Team assembled",
                detail="Invite team members so everyone can collaborate on the workspace.",
                snapshot_field="has_active_team",
                severity="info",
                priority=48,
                banner_title="Invite your team",
                banner_message="Invite teammates so you can collaborate on tasks and updates together.",
            ),
        )
