from components.agents.domain.services.deep.planners import build_plan_from_actions
from components.agents.domain.services.deep.kanban_sync import normalize_task_for_kanban, status_from_column
from components.agents.domain.value_objects.plan_schemas import TaskStatus, Priority


def test_build_plan_from_actions_coerces_fields():
    actions = [
        {
            "title": "Test",
            "priority": "high",
            "status": "done",
            "column_title": "Complete",
            "assignee_type": "agent",
        }
    ]
    plan = build_plan_from_actions(plan_id="plan-1", goal="Goal", actions=actions)
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.priority == Priority.high
    assert task.status == TaskStatus.done
    assert task.column and task.column.title == "Complete"
    assert task.assignee_type.value == "agent"


def test_normalize_task_for_kanban_maps_defaults():
    actions = [{"title": "Task A"}]
    plan = build_plan_from_actions(plan_id="plan-2", goal="Goal", actions=actions)
    task = plan.tasks[0]
    normalized = normalize_task_for_kanban(task)
    assert normalized["status"] == "todo"
    assert normalized["column_title"] in {"Todo", "Backlog", "Complete", "Canceled"}


def test_status_from_column_handles_common_titles():
    assert status_from_column("Complete") == TaskStatus.done
    assert status_from_column("Canceled") == TaskStatus.archived
    assert status_from_column("In Progress") == TaskStatus.todo

