from components.shared_kernel.application.use_cases.notify_task_assignment_change_use_case import (
    NotifyTaskAssignmentChangeUseCase,
)


class _FakeTaskAssignmentNotificationPort:
    def __init__(self) -> None:
        self.calls = []

    def notify_assignment_change(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_notify_task_assignment_change_use_case_delegates_to_port():
    port = _FakeTaskAssignmentNotificationPort()
    use_case = NotifyTaskAssignmentChangeUseCase(
        task_assignment_notification_port=port,
    )

    use_case.execute(
        task=object(),
        actor=object(),
        recipient_ids=[1, 2],
        action="post_add",
    )

    assert len(port.calls) == 1
    assert port.calls[0]["recipient_ids"] == [1, 2]
    assert port.calls[0]["action"] == "post_add"
