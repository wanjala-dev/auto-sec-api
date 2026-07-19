from __future__ import annotations

from components.shared_kernel.application.providers.model_notification_registry_provider import (
    register_model_notification_rule,
)
from components.shared_kernel.application.use_cases.notify_task_assignment_change_use_case import (
    NotifyTaskAssignmentChangeUseCase,
)
from components.shared_kernel.infrastructure.adapters.task_assignment_notification_adapter import (
    TaskAssignmentNotificationAdapter,
)
from components.shared_kernel.infrastructure.adapters.task_assignment_signal_adapter import (
    TaskAssignmentSignalAdapter,
)


class NotificationSignalProvider:
    def register_notification_rule(self, rule) -> None:
        register_model_notification_rule(rule)

    def build_task_assignment_change_use_case(self) -> NotifyTaskAssignmentChangeUseCase:
        return NotifyTaskAssignmentChangeUseCase(
            task_assignment_notification_port=TaskAssignmentNotificationAdapter(),
        )

    def connect_task_assignment_signal(self, *, task_model, actor_resolver) -> None:
        TaskAssignmentSignalAdapter().connect(
            task_model=task_model,
            use_case=self.build_task_assignment_change_use_case(),
            actor_resolver=actor_resolver,
        )
