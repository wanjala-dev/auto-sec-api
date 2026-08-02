"""Use case: resolve a finding board-task (ADR 0012 P4a).

Framework-free orchestration — delegates the resolved-marker write + provenance
stamp + ``FindingResolved`` emission to the injected port. Exists so the project
context owns the finding-resolved transition and other contexts (the remediation
reconciler) reach it through this application surface instead of writing the Task.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.project.application.ports.resolve_finding_task_port import (
    ResolveFindingTaskCommand,
    ResolveFindingTaskPort,
    ResolveFindingTaskResult,
)


@dataclass
class ResolveFindingTaskUseCase:
    port: ResolveFindingTaskPort

    def execute(self, *, command: ResolveFindingTaskCommand) -> ResolveFindingTaskResult:
        return self.port.resolve_finding_task(command=command)
