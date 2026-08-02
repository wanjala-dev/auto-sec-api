"""Provider for the AI Findings workflow-provisioning port.

Wires ``WorkflowProvisioningPort`` to its ORM adapter. The facade consumes this
provider so it never reaches into ``infrastructure`` for the concrete class.
"""

from __future__ import annotations

from components.workflow.application.ports.workflow_provisioning_port import (
    WorkflowProvisioningPort,
)


class WorkflowProvisioningProvider:
    def port(self) -> WorkflowProvisioningPort:
        from components.workflow.infrastructure.repositories.workflow_provisioning_repository import (
            WorkflowProvisioningRepository,
        )

        return WorkflowProvisioningRepository()


_default = WorkflowProvisioningProvider()


def get_workflow_provisioning_provider() -> WorkflowProvisioningProvider:
    return _default
