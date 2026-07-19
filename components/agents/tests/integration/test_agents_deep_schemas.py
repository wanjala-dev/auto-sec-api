from datetime import datetime

from components.agents.domain.value_objects.plan_schemas import (
    TaskSpec,
    Priority,
    TaskStatus,
    AssigneeType,
)


def test_task_spec_defaults():
    task = TaskSpec(title="Test")
    assert task.priority == Priority.medium
    assert task.status == TaskStatus.todo
    assert task.assignee_type == AssigneeType.human


def test_task_spec_parses_due_date_iso():
    task = TaskSpec(title="Test", due_date=datetime.fromisoformat("2026-01-10T00:00:00"))
    assert task.due_date.year == 2026

