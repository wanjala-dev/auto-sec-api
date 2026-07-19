"""Application-layer facade exposing team notification services to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
from components.team.infrastructure.adapters.utilities import (
    send_task_assignment_notification,
)

__all__ = ["send_task_assignment_notification"]
