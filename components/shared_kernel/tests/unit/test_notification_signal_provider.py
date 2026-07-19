from components.shared_kernel.application.use_cases.notify_task_assignment_change_use_case import (
    NotifyTaskAssignmentChangeUseCase,
)
from components.shared_kernel.application.providers.notification_signal_provider import (
    NotificationSignalProvider,
)
from components.shared_kernel.infrastructure.adapters.task_assignment_notification_adapter import (
    TaskAssignmentNotificationAdapter,
)


def test_notification_signal_provider_registers_notification_rule(monkeypatch):
    provider = NotificationSignalProvider()
    captured = {}

    monkeypatch.setattr(
        "components.shared_kernel.application.providers.notification_signal_provider.register_model_notification_rule",
        lambda rule: captured.setdefault("rule", rule),
    )

    rule = object()
    provider.register_notification_rule(rule)

    assert captured["rule"] is rule


def test_notification_signal_provider_builds_task_assignment_use_case():
    provider = NotificationSignalProvider()

    use_case = provider.build_task_assignment_change_use_case()

    assert isinstance(use_case, NotifyTaskAssignmentChangeUseCase)
    assert isinstance(
        use_case.task_assignment_notification_port,
        TaskAssignmentNotificationAdapter,
    )


def test_notification_signal_provider_connects_task_assignment_signal(monkeypatch):
    provider = NotificationSignalProvider()
    captured = {}

    class _Adapter:
        def connect(self, *, task_model, use_case, actor_resolver) -> None:
            captured["task_model"] = task_model
            captured["use_case"] = use_case
            captured["actor_resolver"] = actor_resolver

    monkeypatch.setattr(
        "components.shared_kernel.application.providers.notification_signal_provider.TaskAssignmentSignalAdapter",
        lambda: _Adapter(),
    )

    task_model = object()
    actor_resolver = object()
    provider.connect_task_assignment_signal(
        task_model=task_model,
        actor_resolver=actor_resolver,
    )

    assert captured["task_model"] is task_model
    assert isinstance(captured["use_case"], NotifyTaskAssignmentChangeUseCase)
    assert captured["actor_resolver"] is actor_resolver
