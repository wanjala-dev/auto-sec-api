"""Application-layer facade exposing project serializers to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""

from components.project.mappers.rest.board_view_serializers import (
    BoardViewSerializer,
    WorkflowStatusLaneSerializer,
)
from components.project.mappers.rest.project_serializers import (
    ColumnSerializer,
    ProjectEntrySerializer,
    ProjectGetSerializer,
    ProjectMilestoneSerializer,
    ProjectSerializer,
    ProjectUpdateSerializer,
    TaskCommentSerializer,
    TaskSerializer,
)

__all__ = [
    "BoardViewSerializer",
    "ColumnSerializer",
    "ProjectEntrySerializer",
    "ProjectGetSerializer",
    "ProjectMilestoneSerializer",
    "ProjectSerializer",
    "ProjectUpdateSerializer",
    "TaskCommentSerializer",
    "TaskSerializer",
    "WorkflowStatusLaneSerializer",
]
