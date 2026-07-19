"""Task-related detectors for Orchestrator automations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult, DetectorSignal
from components.agents.infrastructure.adapters.actions.detectors import registry
from components.agents.infrastructure.tasks.service_tasks import ensure_default_columns
from infrastructure.persistence.project.models import Column, ProjectEntry, Task


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _safe_localtime(dt: datetime) -> datetime:
    """Return localized datetime even if the input is naive."""
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_default_timezone())
    return timezone.localtime(dt)


class TaskStagnationDetector(BaseDetector):
    """Detect tasks with active work that are still sitting in the backlog/TODO column."""

    slug = "task_stagnation"
    name = "Task Progress Monitor"
    cadence = "quarter-hour"
    description = "Moves tasks with tracked time into the In Progress column and logs the automation."
    default_config = {
        'hours_threshold': 0,
        'target_column': 'In Progress',
        'fallback_column': 'Backlog',
    }

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        cutoff = self._resolve_cutoff()
        tasks = list(self._fetch_candidates(context.workspace_id, cutoff))
        logger.info(
            "[task_stagnation][signals] workspace=%s candidates=%s cutoff=%s",
            context.workspace_id,
            len(tasks),
            cutoff.isoformat() if cutoff else "none",
        )
        signals: List[DetectorSignal] = []
        for task in tasks:
            signals.append(DetectorSignal(
                signal_type='task.stagnation',
                payload={
                    'task_id': str(task.id),
                    'title': task.title,
                    'current_column': task.column.title if task.column else None,
                    'project': task.project.title if task.project else None,
                }
            ))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        cutoff = self._resolve_cutoff()
        tasks = list(self._fetch_candidates(context.workspace_id, cutoff))
        logger.info(
            "[task_stagnation] workspace=%s candidates=%s cutoff=%s",
            context.workspace_id,
            len(tasks),
            cutoff.isoformat() if cutoff else "none",
        )
        results: List[DetectorResult] = []

        for task in tasks:
            target_column = self._resolve_target_column(task)
            if not target_column:
                logger.info(
                    "[task_stagnation] workspace=%s task=%s skipped=no_target_column",
                    context.workspace_id,
                    task.id,
                )
                continue  # Cannot determine a safe column change

            previous_column = task.column.title if task.column else None
            if previous_column == target_column.title:
                logger.info(
                    "[task_stagnation] workspace=%s task=%s already_in_target=%s",
                    context.workspace_id,
                    task.id,
                    target_column.title,
                )
                continue

            with transaction.atomic():
                task.column = target_column
                task.save(update_fields=['column', 'updated_at'])
            logger.info(
                "[task_stagnation] workspace=%s task=%s moved %s -> %s",
                context.workspace_id,
                task.id,
                previous_column,
                target_column.title,
            )

            default_title = f"Moved task '{task.title}' to {target_column.title}"
            default_summary = (
                f"Moved task '{task.title}' to {target_column.title} after detecting tracked time "
                f"while it was still in {previous_column or 'no column'}"
            )
            agent_output = None
            title = default_title
            summary = default_summary
            if context.invoke_agent:
                agent_context = {
                    'task': {
                        'id': str(task.id),
                        'title': task.title,
                        'previous_column': previous_column,
                        'new_column': target_column.title,
                        'project': task.project.title if task.project else None,
                        'status': task.status,
                    },
                    'instruction': "Return JSON with keys 'title' and 'summary' explaining the move and follow-up guidance.",
                }
                try:
                    agent_result = context.invoke_agent(
                        'task_agent',
                        (
                            "Explain for the admin why this task was moved to the In Progress column and what to do next. "
                            "Respond strictly as JSON with keys 'title' and 'summary'."
                        ),
                        agent_context,
                    )
                    agent_text = agent_result.get('result') if isinstance(agent_result, dict) else str(agent_result)
                    if agent_text:
                        try:
                            parsed = json.loads(agent_text)
                        except json.JSONDecodeError:
                            parsed = {
                                'title': title,
                                'summary': agent_text.strip() or summary,
                            }
                        agent_output = parsed
                        title = parsed.get('title', title)
                        summary = parsed.get('summary', summary)
                except Exception as exc:  # pragma: no cover
                    logger.exception("[task_stagnation] agent call failed for task %s: %s", task.id, exc)

            payload = {
                'task_id': str(task.id),
                'task_title': task.title,
                'previous_column': previous_column,
                'new_column': target_column.title,
                'project': task.project.title if task.project else None,
                'agent_output': agent_output,
            }

            results.append(DetectorResult(
                action_type='task.auto_move_to_in_progress',
                title=title,
                summary=summary,
                payload=payload,
                context={'task_id': str(task.id)},
                status="auto_executed",
                auto_execute=True,
                detector_slug=self.slug,
                agent_type='task_agent',
                metadata={'impact_score': 1},
            ))

        logger.info("[task_stagnation] workspace=%s actions=%s", context.workspace_id, len(results))
        return results

    def _resolve_cutoff(self) -> Optional[datetime]:
        hours = self.config.get('hours_threshold')
        try:
            hours_value = int(hours)
        except (TypeError, ValueError):
            return None
        if hours_value <= 0:
            return None
        return timezone.now() - timedelta(hours=hours_value)

    def _fetch_candidates(self, workspace_id: str, cutoff: Optional[datetime]) -> Iterable[Task]:
        recent_work = ProjectEntry.objects.filter(
            task=OuterRef('pk'),
            minutes__gt=0,
            is_tracked=False,
        )
        if cutoff:
            recent_work = recent_work.filter(created_at__gte=cutoff)

        now_dt = timezone.now()
        if timezone.is_naive(now_dt):
            today_floor = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            now_local = _safe_localtime(now_dt)
            today_floor = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        # Ensure we catch tracked sessions logged earlier in the day even if older than the cutoff window.
        same_day_work = ProjectEntry.objects.filter(
            task=OuterRef('pk'),
            minutes__gt=0,
            is_tracked=False,
            created_at__gte=today_floor,
        )

        active_timers = ProjectEntry.objects.filter(
            task=OuterRef('pk'),
            is_tracked=True,
        )

        return Task.objects.filter(
            workspace_id=workspace_id,
            status=Task.TODO,
        ).annotate(
            has_recent_work=Exists(recent_work),
            has_today_work=Exists(same_day_work),
            has_active_timer=Exists(active_timers),
        ).filter(
            Q(has_active_timer=True) | Q(has_recent_work=True) | Q(has_today_work=True)
        ).select_related('project', 'column', 'team')

    def _resolve_target_column(self, task: Task) -> Optional[Column]:
        target_title = self.config.get('target_column', 'In Progress')
        fallback_title = self.config.get('fallback_column', 'Backlog')

        if task.project:
            columns = ensure_default_columns(task.project)
            target = columns.get(target_title) or columns.get(fallback_title)
            return target

        # Tasks without a project: fall back to workspace/team-wide columns
        column = Column.objects.filter(
            workspace=task.workspace,
            team=task.team,
            title__iexact=target_title,
            project__isnull=True,
        ).first()
        if column:
            return column
        fallback = Column.objects.filter(
            workspace=task.workspace,
            team=task.team,
            title__iexact=fallback_title,
            project__isnull=True,
        ).first()
        if fallback:
            return fallback

        # Create a neutral column for non-project tasks
        return Column.objects.create(
            workspace=task.workspace,
            team=task.team,
            project=None,
            title=target_title,
            order=1,
            created_by=task.created_by,
        )


registry.register(TaskStagnationDetector)


def _action_exists(workspace_id: str, action_type: str, task_id: str) -> bool:
    from infrastructure.persistence.project.models import Task
    return Task.objects.filter(
        workspace_id=workspace_id,
        source_type=f"ai.{action_type}",
        metadata__idempotency_key=f"task_id:{task_id}",
    ).exists()


class TaskInactivityDetector(BaseDetector):
    slug = "task.inactivity"
    name = "Stalled Task Notifier"
    cadence = "daily"
    description = "Flags tasks with no updates for an extended period."
    default_config = {
        'days_threshold': 7,
    }

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        cutoff = timezone.now() - timedelta(days=int(self.config.get('days_threshold', 7)))
        tasks = Task.objects.filter(
            workspace_id=context.workspace_id,
            status=Task.TODO,
            updated_at__lte=cutoff,
        ).select_related('project')
        logger.info(
            "[task_inactivity][signals] workspace=%s candidates=%s cutoff=%s",
            context.workspace_id,
            tasks.count(),
            cutoff.isoformat(),
        )
        signals: List[DetectorSignal] = []
        for task in tasks:
            signals.append(DetectorSignal(
                signal_type='task.inactivity',
                payload={
                    'task_id': str(task.id),
                    'title': task.title,
                    'project': task.project.title if task.project else None,
                    'last_updated': task.updated_at.isoformat(),
                }
            ))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        cutoff = timezone.now() - timedelta(days=int(self.config.get('days_threshold', 7)))
        tasks = Task.objects.filter(
            workspace_id=context.workspace_id,
            status=Task.TODO,
            updated_at__lte=cutoff,
        ).select_related('project')

        results: List[DetectorResult] = []
        for task in tasks:
            task_id = str(task.id)
            if _action_exists(context.workspace_id, 'task.inactivity', task_id):
                continue

            if not task.requires_review:
                task.requires_review = True
                task.save(update_fields=['requires_review', 'updated_at'])

            default_summary = f"Task '{task.title}' has been idle for more than {self.config.get('days_threshold', 7)} days."
            default_title = f"Task '{task.title}' flagged for review"
            summary = default_summary
            title = default_title
            agent_output = None

            if context.invoke_agent:
                agent_context = {
                    'task': {
                        'id': task_id,
                        'title': task.title,
                        'project': task.project.title if task.project else None,
                        'last_updated': task.updated_at.isoformat(),
                    },
                    'instruction': "Return JSON with keys 'title' and 'summary' advising the admin on this stalled task.",
                }
                try:
                    agent_result = context.invoke_agent(
                        'task_agent',
                        (
                            "Offer guidance for resolving or progressing this stalled task. "
                            "Respond strictly as JSON with keys 'title' and 'summary'."
                        ),
                        agent_context,
                    )
                    agent_text = agent_result.get('result') if isinstance(agent_result, dict) else str(agent_result)
                    if agent_text:
                        try:
                            parsed = json.loads(agent_text)
                        except json.JSONDecodeError:
                            parsed = {
                                'title': title,
                                'summary': agent_text.strip() or summary,
                            }
                        agent_output = parsed
                        title = parsed.get('title', title)
                        summary = parsed.get('summary', summary)
                except Exception as exc:  # pragma: no cover
                    logger.exception("[task_inactivity] agent call failed for task %s: %s", task_id, exc)

            payload = {
                'task_id': task_id,
                'task_title': task.title,
                'project': task.project.title if task.project else None,
                'agent_output': agent_output,
            }

            results.append(DetectorResult(
                action_type='task.inactivity',
                title=title,
                summary=summary,
                payload=payload,
                context={'task_id': task_id},
                status="auto_executed",
                auto_execute=True,
                detector_slug=self.slug,
                agent_type='task_agent',
                metadata={'impact_score': 1},
            ))

        logger.info("[task_inactivity] workspace=%s flagged=%s", context.workspace_id, len(results))
        return results


class TaskDeadlineSlipDetector(BaseDetector):
    slug = "task.deadline_slip"
    name = "Deadline Slip Monitor"
    cadence = "hourly"
    description = "Escalates TODO tasks that are close to their due date."
    default_config = {
        'hours_threshold': 48,
        'escalated_priority': Task.Priority.HIGH,
    }

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        if not hasattr(Task, 'due_date'):
            return []
        window = timezone.now() + timedelta(hours=int(self.config.get('hours_threshold', 48)))
        tasks = Task.objects.filter(
            workspace_id=context.workspace_id,
            status=Task.TODO,
            due_date__isnull=False,
            due_date__lte=window,
        ).select_related('project')
        logger.info(
            "[task_deadline_slip][signals] workspace=%s candidates=%s window=%s",
            context.workspace_id,
            tasks.count(),
            window.isoformat(),
        )
        signals: List[DetectorSignal] = []
        for task in tasks:
            signals.append(DetectorSignal(
                signal_type='task.deadline_slip',
                payload={
                    'task_id': str(task.id),
                    'title': task.title,
                    'project': task.project.title if task.project else None,
                    'due_date': task.due_date.isoformat() if task.due_date else None,
                    'priority': task.priority,
                }
            ))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        if not hasattr(Task, 'due_date'):
            return []

        window = timezone.now() + timedelta(hours=int(self.config.get('hours_threshold', 48)))
        tasks = list(Task.objects.filter(
            workspace_id=context.workspace_id,
            status=Task.TODO,
            due_date__isnull=False,
            due_date__lte=window,
            due_date__gte=timezone.now(),
        ).select_related('project'))
        logger.info("[task_deadline_slip] workspace=%s candidates=%s window=%s", context.workspace_id, len(tasks), window)

        results: List[DetectorResult] = []
        for task in tasks:
            task_id = str(task.id)
            if _action_exists(context.workspace_id, 'task.deadline_slip', task_id):
                continue

            updated_fields = []
            if task.priority != self.config.get('escalated_priority', Task.Priority.HIGH):
                task.priority = self.config.get('escalated_priority', Task.Priority.HIGH)
                updated_fields.append('priority')
            if not task.requires_review:
                task.requires_review = True
                updated_fields.append('requires_review')
            if updated_fields:
                task.save(update_fields=updated_fields + ['updated_at'])

            default_summary = (
                f"Task '{task.title}' is due soon ({task.due_date.strftime('%Y-%m-%d %H:%M')}) and is still TODO."
            )
            default_title = f"Escalated task '{task.title}' for imminent deadline"
            summary = default_summary
            title = default_title
            agent_output = None

            if context.invoke_agent:
                agent_context = {
                    'task': {
                        'id': task_id,
                        'title': task.title,
                        'due_date': task.due_date.isoformat() if task.due_date else None,
                        'priority': task.priority,
                        'project': task.project.title if task.project else None,
                    },
                    'instruction': "Return JSON with keys 'title' and 'summary' describing this deadline risk and recommended follow-up.",
                }
                try:
                    agent_result = context.invoke_agent(
                        'task_agent',
                        (
                            "Provide a concise alert about the approaching deadline and advise on next steps. "
                            "Respond strictly as JSON with keys 'title' and 'summary'."
                        ),
                        agent_context,
                    )
                    agent_text = agent_result.get('result') if isinstance(agent_result, dict) else str(agent_result)
                    if agent_text:
                        parsed = json.loads(agent_text)
                        agent_output = parsed
                        title = parsed.get('title', title)
                        summary = parsed.get('summary', summary)
                except Exception as exc:  # pragma: no cover
                    logger.exception("[task_deadline_slip] agent call failed for task %s: %s", task_id, exc)

            payload = {
                'task_id': task_id,
                'task_title': task.title,
                'due_date': task.due_date.isoformat() if task.due_date else None,
                'priority': task.priority,
                'project': task.project.title if task.project else None,
                'agent_output': agent_output,
                'lookup_key': task_id,
            }

            results.append(DetectorResult(
                action_type='task.deadline_slip',
                title=title,
                summary=summary,
                payload=payload,
                context={'task_id': task_id},
                status="auto_executed",
                auto_execute=True,
                detector_slug=self.slug,
                agent_type='task_agent',
                metadata={'impact_score': 2},
            ))

        logger.info("[task_deadline_slip] workspace=%s escalated=%s", context.workspace_id, len(results))
        return results


class TaskNoOwnerDetector(BaseDetector):
    slug = "task.no_owner"
    name = "Unowned Task Assignee"
    cadence = "hourly"
    description = "Ensures tasks have an owner or surfaces them for triage."

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        tasks = Task.objects.filter(
            workspace_id=context.workspace_id,
        ).filter(
            Q(assigned_to__isnull=True) | Q(project__isnull=True)
        ).select_related('project').distinct()
        return [
            DetectorSignal(
                signal_type='task.no_owner',
                payload={
                    'task_id': str(task.id),
                    'title': task.title,
                    'project': task.project.title if task.project else None,
                    'missing_owner': not task.assigned_to.exists(),
                    'missing_project': task.project_id is None,
                }
            )
            for task in tasks
        ]

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        tasks = list(
            Task.objects.filter(workspace_id=context.workspace_id)
            .filter(Q(assigned_to__isnull=True) | Q(project__isnull=True))
            .select_related('project', 'project__lead')
            .prefetch_related('assigned_to')
            .distinct()
        )
        logger.info("[task_no_owner] workspace=%s untriaged=%s", context.workspace_id, len(tasks))

        results: List[DetectorResult] = []
        for task in tasks:
            task_id = str(task.id)
            if _action_exists(context.workspace_id, 'task.no_owner', task_id):
                continue

            missing_owner = not task.assigned_to.exists()
            missing_project = task.project_id is None

            if missing_owner and task.project and task.project.lead:
                lead = task.project.lead
                task.assigned_to.add(lead)
                task.save(update_fields=['updated_at'])
                default_summary = f"Auto-assigned task '{task.title}' to project lead {lead.get_full_name() or lead.email}."
                default_title = f"Assigned '{task.title}' to project lead"
                summary = default_summary
                title = default_title
                agent_output = None
                if context.invoke_agent:
                    agent_context = {
                        'task': {
                            'id': task_id,
                            'title': task.title,
                            'project': task.project.title,
                        },
                        'assignee': {
                            'name': lead.get_full_name() or lead.email,
                            'email': lead.email,
                        },
                        'instruction': "Return JSON with keys 'title' and 'summary' explaining the reassignment to the project lead.",
                    }
                    try:
                        agent_result = context.invoke_agent(
                            'task_agent',
                            (
                                "Confirm for the admin that the project lead has been assigned this task. "
                                "Respond strictly as JSON with keys 'title' and 'summary'."
                            ),
                            agent_context,
                        )
                        agent_text = agent_result.get('result') if isinstance(agent_result, dict) else str(agent_result)
                        if agent_text:
                            parsed = json.loads(agent_text)
                            agent_output = parsed
                            title = parsed.get('title', title)
                            summary = parsed.get('summary', summary)
                    except Exception as exc:  # pragma: no cover
                        logger.exception("[task_no_owner] agent call failed for task %s: %s", task_id, exc)

                payload = {
                    'task_id': task_id,
                    'task_title': task.title,
                    'assigned_to': lead.email,
                    'project': task.project.title,
                    'missing_owner': missing_owner,
                    'missing_project': missing_project,
                    'agent_output': agent_output,
                }
                auto_execute = True
                status_value = "auto_executed"
            else:
                if not task.requires_review:
                    task.requires_review = True
                    task.save(update_fields=['requires_review', 'updated_at'])

                summary_parts: List[str] = []
                if missing_owner:
                    summary_parts.append(
                        "Task has no owner and no project lead to fall back on."
                    )
                if missing_project:
                    summary_parts.append(
                        "Task is not assigned to any project, so it will not appear in project workflows."
                    )
                if not summary_parts:
                    summary_parts.append("Review task ownership and project assignment.")

                default_summary = " ".join(summary_parts) + " Assign it to a teammate or move it to the backlog if it is no longer needed."
                default_title = f"Triage task '{task.title}'"
                summary = default_summary
                title = default_title
                agent_output = {
                    'title': default_title,
                    'summary': default_summary,
                }
                payload = {
                    'task_id': task_id,
                    'task_title': task.title,
                    'project': task.project.title if task.project else None,
                    'missing_owner': missing_owner,
                    'missing_project': missing_project,
                    'agent_output': agent_output,
                }
                auto_execute = False
                status_value = "pending"

            results.append(DetectorResult(
                action_type='task.no_owner',
                title=title,
                summary=summary,
                payload=payload,
                context={'task_id': task_id},
                status=status_value,
                auto_execute=auto_execute,
                detector_slug=self.slug,
                agent_type='task_agent',
                metadata={'impact_score': 1},
            ))

        logger.info("[task_no_owner] workspace=%s actions=%s", context.workspace_id, len(results))
        return results


class TaskTestingWithoutWorkDetector(BaseDetector):
    slug = "task.testing_without_work"
    name = "Testing Column Work Check"
    cadence = "quarter-hour"
    description = "Flags Testing column tasks that have no tracked time or active timer."
    default_config = {
        'testing_column_title': 'Testing',
    }

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        tasks = list(self._fetch_candidates(context.workspace_id))
        logger.info(
            "[task_testing_without_work][signals] workspace=%s candidates=%s",
            context.workspace_id,
            len(tasks),
        )
        signals: List[DetectorSignal] = []
        for task in tasks:
            signals.append(DetectorSignal(
                signal_type=self.slug,
                payload={
                    'task_id': str(task.id),
                    'title': task.title,
                    'project': task.project.title if task.project else None,
                    'column': task.column.title if task.column else None,
                }
            ))
        return signals

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        tasks = list(self._fetch_candidates(context.workspace_id))
        logger.info(
            "[task_testing_without_work] workspace=%s candidates=%s",
            context.workspace_id,
            len(tasks),
        )

        results: List[DetectorResult] = []
        for task in tasks:
            task_id = str(task.id)
            if _action_exists(context.workspace_id, self.slug, task_id):
                continue

            if not task.requires_review:
                task.requires_review = True
                task.save(update_fields=['requires_review', 'updated_at'])

            default_title = f"Investigate task '{task.title}' in Testing"
            default_summary = (
                f"Task '{task.title}' is in the Testing column but has no tracked time or active timer. "
                f"Confirm whether it is ready for testing or move it back to an earlier stage."
            )
            title = default_title
            summary = default_summary
            agent_output = None

            if context.invoke_agent:
                agent_context = {
                    'task': {
                        'id': task_id,
                        'title': task.title,
                        'project': task.project.title if task.project else None,
                        'column': task.column.title if task.column else None,
                    },
                    'instruction': (
                        "Return JSON with keys 'title' and 'summary' explaining why a task without tracked work "
                        "should not be in the Testing column and what to do next."
                    ),
                }
                try:
                    agent_result = context.invoke_agent(
                        'task_agent',
                        (
                            "Advise the admin how to handle a task in Testing that has no tracked time. "
                            "Respond strictly as JSON with keys 'title' and 'summary'."
                        ),
                        agent_context,
                    )
                    agent_text = agent_result.get('result') if isinstance(agent_result, dict) else str(agent_result)
                    if agent_text:
                        parsed = json.loads(agent_text)
                        agent_output = parsed
                        title = parsed.get('title', title)
                        summary = parsed.get('summary', summary)
                except Exception as exc:  # pragma: no cover
                    logger.exception("[task_testing_without_work] agent call failed for task %s: %s", task_id, exc)

            payload = {
                'task_id': task_id,
                'task_title': task.title,
                'project': task.project.title if task.project else None,
                'column': task.column.title if task.column else None,
                'agent_output': agent_output,
            }

            results.append(DetectorResult(
                action_type=self.slug,
                title=title,
                summary=summary,
                payload=payload,
                context={'task_id': task_id},
                status="pending",
                auto_execute=False,
                detector_slug=self.slug,
                agent_type='task_agent',
                metadata={'impact_score': 1},
            ))

        logger.info("[task_testing_without_work] workspace=%s actions=%s", context.workspace_id, len(results))
        return results

    def _fetch_candidates(self, workspace_id: str) -> Iterable[Task]:
        testing_title = (self.config.get('testing_column_title') or 'Testing').strip()
        if not testing_title:
            return Task.objects.none()

        logged_work = ProjectEntry.objects.filter(
            task=OuterRef('pk'),
            minutes__gt=0,
        )
        active_timers = ProjectEntry.objects.filter(
            task=OuterRef('pk'),
            is_tracked=True,
        )

        return Task.objects.filter(
            workspace_id=workspace_id,
            status=Task.TODO,
            column__title__iexact=testing_title,
        ).annotate(
            has_logged_work=Exists(logged_work),
            has_active_timer=Exists(active_timers),
        ).filter(
            Q(has_logged_work=False) & Q(has_active_timer=False)
        ).select_related('project', 'column')


registry.register(TaskInactivityDetector)
registry.register(TaskDeadlineSlipDetector)
registry.register(TaskNoOwnerDetector)
registry.register(TaskTestingWithoutWorkDetector)
