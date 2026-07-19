"""Resource DTOs (output schemas) for the project bounded context."""

from __future__ import annotations

from .project_resource import ProjectResource, ProjectCollectionResource
from .task_resource import TaskResource, TaskCollectionResource
from .column_resource import ColumnResource, ColumnCollectionResource
from .project_update_resource import ProjectUpdateResource, ProjectUpdateCollectionResource
from .milestone_resource import MilestoneResource, MilestoneCollectionResource
from .task_comment_resource import TaskCommentResource, TaskCommentCollectionResource
from .timer_entry_resource import TimerEntryResource

__all__ = [
    "ProjectResource",
    "ProjectCollectionResource",
    "TaskResource",
    "TaskCollectionResource",
    "ColumnResource",
    "ColumnCollectionResource",
    "ProjectUpdateResource",
    "ProjectUpdateCollectionResource",
    "MilestoneResource",
    "MilestoneCollectionResource",
    "TaskCommentResource",
    "TaskCommentCollectionResource",
    "TimerEntryResource",
]
