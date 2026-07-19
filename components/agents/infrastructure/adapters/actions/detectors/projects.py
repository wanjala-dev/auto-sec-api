"""Project-related detectors for milestones and updates."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult, DetectorSignal
from components.agents.infrastructure.adapters.actions.detectors import registry
from infrastructure.persistence.project.models import Project, ProjectMilestone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _action_exists(workspace_id: str, action_type: str, lookup_key: str) -> bool:
    from infrastructure.persistence.project.models import Task

    return Task.objects.filter(
        workspace_id=workspace_id,
        source_type=f"ai.{action_type}",
        metadata__idempotency_key=f"lookup_key:{lookup_key}",
    ).exists()


class MilestoneReminderDetector(BaseDetector):
    slug = "project.milestone_due"
    name = "Milestone Reminder"
    cadence = "daily"
    description = "Flags project milestones due soon."
    default_config = {
        "days_ahead": 7,
        "max_results": 10,
    }

    def gather_signals(self, context: DetectorContext) -> list[DetectorSignal]:
        days_ahead = int(self.config.get("days_ahead", 7))
        limit = int(self.config.get("max_results", 10))
        now = timezone.now().date()
        upcoming = now + timedelta(days=days_ahead)

        milestones = ProjectMilestone.objects.filter(
            projects__workspace_id=context.workspace_id,
            target_date__gte=now,
            target_date__lte=upcoming,
        ).distinct()[:limit]

        signals = [
            DetectorSignal(
                "project.milestone_due",
                {
                    "milestone_id": str(m.id),
                    "name": m.name,
                    "target_date": m.target_date.isoformat(),
                },
            )
            for m in milestones
        ]
        logger.info("[milestone_due][signals] workspace=%s count=%s", context.workspace_id, len(signals))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        return []


class ProjectUpdateBacklogDetector(BaseDetector):
    slug = "project.update_backlog"
    name = "Project Update Backlog"
    cadence = "daily"
    description = "Highlights projects without updates in the last N days."
    default_config = {
        "days_without_update": 30,
        "max_results": 10,
    }

    def gather_signals(self, context: DetectorContext) -> list[DetectorSignal]:
        days = int(self.config.get("days_without_update", 30))
        limit = int(self.config.get("max_results", 10))
        cutoff = timezone.now() - timedelta(days=days)

        projects = (
            Project.objects.filter(workspace_id=context.workspace_id)
            .annotate(last_update=Max("project_updates__created_on"))
            .order_by("last_update", "created_at")
        )

        signals: list[DetectorSignal] = []
        for project in projects:
            last_update = project.last_update
            if last_update and last_update >= cutoff:
                continue
            signals.append(
                DetectorSignal(
                    "project.update_backlog",
                    {
                        "project_id": str(project.id),
                        "project_title": project.title,
                        "last_update": last_update.isoformat() if last_update else None,
                        "days_without_update": days,
                        "never_updated": last_update is None,
                    },
                )
            )
            if len(signals) >= limit:
                break
        logger.info("[update_backlog][signals] workspace=%s count=%s", context.workspace_id, len(signals))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        days = int(self.config.get("days_without_update", 30))
        limit = int(self.config.get("max_results", 10))
        cutoff = timezone.now() - timedelta(days=days)
        now = timezone.now()

        projects = (
            Project.objects.filter(workspace_id=context.workspace_id)
            .annotate(last_update=Max("project_updates__created_on"))
            .order_by("last_update", "created_at")
        )

        results: list[DetectorResult] = []
        for project in projects:
            last_update = project.last_update
            if last_update and last_update >= cutoff:
                continue

            lookup_key = f"project-backlog-{project.id}"
            if _action_exists(context.workspace_id, "project.update_backlog", lookup_key):
                continue

            if last_update:
                days_since_update = max(1, (now - last_update).days)
                default_summary = (
                    f"Project '{project.title}' has not been updated for {days_since_update} day"
                    f"{'s' if days_since_update != 1 else ''}. Share progress or note blockers."
                )
            else:
                default_summary = f"Project '{project.title}' has never received an update. Share an initial status to keep the team aligned."
            default_title = f"Project '{project.title}' needs an update"

            summary = default_summary
            title = default_title
            agent_output = None

            payload = {
                "lookup_key": lookup_key,
                "project_id": str(project.id),
                "project_title": project.title,
                "last_update": last_update.isoformat() if last_update else None,
                "days_without_update": days,
                "never_updated": last_update is None,
                "agent_output": agent_output,
            }

            results.append(
                DetectorResult(
                    action_type="project.update_backlog",
                    title=title,
                    summary=summary,
                    payload=payload,
                    context={"project_id": str(project.id)},
                    status="pending",
                    auto_execute=False,
                    detector_slug=self.slug,
                    agent_type="project_agent",
                    metadata={"impact_score": 1},
                )
            )

            if len(results) >= limit:
                break

        logger.info("[project_backlog] workspace=%s actions=%s", context.workspace_id, len(results))
        return results


registry.register(MilestoneReminderDetector)
registry.register(ProjectUpdateBacklogDetector)
