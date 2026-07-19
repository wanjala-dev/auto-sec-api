from __future__ import annotations

from types import SimpleNamespace

from components.shared_kernel.infrastructure.adapters.task_assignment_signal_adapter import (
    TaskAssignmentSignalAdapter,
)


def test_task_assignment_signal_adapter_routes_signal_to_use_case():
    adapter = TaskAssignmentSignalAdapter()
    recorded = {}

    class _UseCase:
        def execute(self, **kwargs):
            recorded.update(kwargs)

    actor = object()
    receiver = adapter._build_handler(
        use_case=_UseCase(),
        actor_resolver=lambda instance: actor,
    )
    task = SimpleNamespace(id="task-1")

    receiver(sender=object(), instance=task, action="post_add", pk_set={1, 2})

    assert recorded["task"] is task
    assert recorded["actor"] is actor
    assert recorded["recipient_ids"] == {1, 2}
    assert recorded["action"] == "post_add"


def test_task_assignment_signal_adapter_ignores_irrelevant_events():
    adapter = TaskAssignmentSignalAdapter()
    called = {"count": 0}

    class _UseCase:
        def execute(self, **kwargs):
            called["count"] += 1

    receiver = adapter._build_handler(
        use_case=_UseCase(),
        actor_resolver=lambda instance: object(),
    )

    receiver(sender=object(), instance=object(), action="pre_add", pk_set={1})
    receiver(sender=object(), instance=object(), action="post_add", pk_set=set())

    assert called["count"] == 0
