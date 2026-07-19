"""Request DTOs (input schemas) for the project bounded context."""

from __future__ import annotations

from .create_project_request import CreateProjectRequest
from .create_task_request import CreateTaskRequest
from .update_task_request import UpdateTaskRequest
from .patch_project_request import PatchProjectRequest
from .create_column_request import CreateColumnRequest
from .update_column_request import UpdateColumnRequest
from .create_project_update_request import CreateProjectUpdateRequest
from .update_project_update_request import UpdateProjectUpdateRequest
from .patch_project_update_request import PatchProjectUpdateRequest
from .create_milestone_request import CreateMilestoneRequest
from .update_milestone_request import UpdateMilestoneRequest
from .create_task_comment_request import CreateTaskCommentRequest
from .assign_users_to_task_request import AssignUsersToTaskRequest
from .start_timer_request import StartTimerRequest
from .stop_timer_request import StopTimerRequest
from .discard_timer_request import DiscardTimerRequest

__all__ = [
    "CreateProjectRequest",
    "CreateTaskRequest",
    "UpdateTaskRequest",
    "PatchProjectRequest",
    "CreateColumnRequest",
    "UpdateColumnRequest",
    "CreateProjectUpdateRequest",
    "UpdateProjectUpdateRequest",
    "PatchProjectUpdateRequest",
    "CreateMilestoneRequest",
    "UpdateMilestoneRequest",
    "CreateTaskCommentRequest",
    "AssignUsersToTaskRequest",
    "StartTimerRequest",
    "StopTimerRequest",
    "DiscardTimerRequest",
]
