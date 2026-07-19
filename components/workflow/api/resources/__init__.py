"""Resource DTOs (output schemas) for the workflow bounded context."""

from __future__ import annotations

from .workflow_resource import (
    WorkflowResource,
    WorkflowSummaryResource,
    WorkflowCollectionResource,
)
from .workflow_template_resource import (
    WorkflowTemplateResource,
    WorkflowTemplateCollectionResource,
)
from .workflow_run_resource import WorkflowRunResource, WorkflowRunCollectionResource
from .workflow_binding_resource import (
    WorkflowBindingResource,
    WorkflowBindingCollectionResource,
)
from .workflow_enrollment_resource import (
    WorkflowEnrollmentResource,
    WorkflowEnrollmentCollectionResource,
)
from .workflow_step_event_resource import (
    WorkflowStepEventResource,
    WorkflowStepEventCollectionResource,
)

__all__ = [
    "WorkflowResource",
    "WorkflowSummaryResource",
    "WorkflowCollectionResource",
    "WorkflowTemplateResource",
    "WorkflowTemplateCollectionResource",
    "WorkflowRunResource",
    "WorkflowRunCollectionResource",
    "WorkflowBindingResource",
    "WorkflowBindingCollectionResource",
    "WorkflowEnrollmentResource",
    "WorkflowEnrollmentCollectionResource",
    "WorkflowStepEventResource",
    "WorkflowStepEventCollectionResource",
]
