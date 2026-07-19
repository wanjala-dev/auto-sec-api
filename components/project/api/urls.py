#
# Import Django

from django.urls import path, re_path

#
# Import views
from components.project.api.controller import (
    AssignedTasksView,
    AssignUsersToTaskView,
    BatchMoveTasksView,
    ColumnDetailView,
    ColumnReorderView,
    ColumnsView,
    DiscardTimerView,
    MilestoneDetailView,
    MilestonesView,
    ProjectDetailView,
    ProjectPatchView,
    ProjectsView,
    ProjectUpdateDetailView,
    ProjectUpdatesView,
    ProjectView,
    StartTimerView,
    StopTimerView,
    TaskCommentDetailView,
    TaskCommentListCreateView,
    TaskDetailView,
    TasksForEntityView,
    TaskUpdateView,
)

# from .api import api_start_timer, api_stop_timer, api_discard_timer, api_get_tasks
# from .views import projects, project, edit_project, task, edit_task, edit_entry, delete_entry, delete_untracked_entry, track_entry


#
# Url pattern

app_name = "project"
urlpatterns = [
    # Project updates and Milestones (place these FIRST)
    path("updates/", ProjectUpdatesView.as_view(), name="project_updates"),
    path("updates/<int:update_id>/", ProjectUpdateDetailView.as_view(), name="project_update_detail"),
    path("updates/project/<int:project_id>/", ProjectUpdatesView.as_view(), name="project_updates_by_project"),
    path("milestones/", MilestonesView.as_view(), name="milestones"),
    path("milestones/<int:milestone_id>/", MilestoneDetailView.as_view(), name="milestone_detail"),
    path("milestones/project/<int:project_id>/", MilestonesView.as_view(), name="milestones_by_project"),
    # Columns routes (more specific)
    path("columns/", ColumnsView.as_view(), name="columns"),
    path("columns/reorder/", ColumnReorderView.as_view(), name="column-reorder"),
    path("columns/<int:column_id>/", ColumnDetailView.as_view(), name="column-detail"),
    path(
        "columns/project/<int:project_id>/team/<int:team_id>/workspaces/<uuid:workspace_id>/",
        ColumnsView.as_view(),
        name="columns-by-project-team-workspace",
    ),
    path(
        "columns/team/<int:team_id>/workspaces/<uuid:workspace_id>/",
        ColumnsView.as_view(),
        name="columns-by-team-workspace",
    ),
    path("columns/team/<int:team_id>/", ColumnsView.as_view(), name="columns-by-team"),
    path("columns/workspaces/<uuid:workspace_id>/", ColumnsView.as_view(), name="columns-by-workspace"),
    path("tasks/batch-move/", BatchMoveTasksView.as_view(), name="batch-move-tasks"),
    path("tasks/timer/start_timer/", StartTimerView.as_view(), name="api_start_timer"),
    path("tasks/timer/stop_timer/", StopTimerView.as_view(), name="api_stop_timer"),
    path("tasks/timer/discard_timer/", DiscardTimerView.as_view(), name="api_discard_timer"),
    # Tasks filtered by associated entity
    path("tasks/grant/<uuid:grant_id>/", TasksForEntityView.as_view(), name="tasks-by-grant"),
    # Tasks assigned to the current user, across ALL teams in a workspace ("My Work")
    path("tasks/assigned-to-me/<uuid:workspace_id>/", AssignedTasksView.as_view(), name="tasks-assigned-to-me"),
    # Task creation (column-based — resolves team from column)
    path("task/", ProjectView.as_view(), name="create-task"),
    # projects
    path("", ProjectsView.as_view(), name=ProjectsView.name),
    path("task/<int:project_id>/<str:uuid>/<int:task_id>", TaskDetailView.as_view(), name=TaskDetailView.name),
    path("workspaces/<uuid:workspace>/", ProjectsView.as_view(), name="projects-by-workspace"),
    path(
        "workspaces/<uuid:workspace_id>/team/<int:team>/", ProjectsView.as_view(), name="project_by_workspace_and_team"
    ),
    path("user/<uuid:uuid>/", ProjectsView.as_view(), name="projects-by-user"),
    # post task
    path("patch/<int:project_id>/", ProjectPatchView.as_view(), name="project_patch"),
    # path('tasks/<int:project_id>/<str:uuid>/', TasksView.as_view(), name= TasksView.name),
    path("task/update/<str:uuid>/<str:task_id>/", TaskDetailView.as_view(), name="update-task"),
    re_path(r"^(?:(?P<project_id>\d+)/)?(?P<uuid>[\w-]+)/$", ProjectDetailView.as_view(), name=ProjectView.name),
    path("tasks/<int:task_id>/", TaskUpdateView.as_view(), name="task-update-by-id"),
    path("tasks/<int:task_id>/update/", ProjectView.as_view(), name="update-task"),
    path("user/<str:uuid>/workspaces/<str:workspace>/", ProjectsView.as_view(), name=ProjectsView.name),
    path("tasks/<int:task_id>/comments/", TaskCommentListCreateView.as_view(), name="task-comments"),
    path("tasks/<int:task_id>/comments/<int:comment_id>/", TaskCommentDetailView.as_view(), name="task-comment-detail"),
    path("tasks/<int:task_id>/assign/", AssignUsersToTaskView.as_view(), name="assign-users-to-task"),
    # path('', projects, name='projects'),
    # path('<int:project_id>/', project, name='project'),
    # path('<int:project_id>/<int:task_id>/', task, name='task'),
    # path('<int:project_id>/<int:task_id>/<int:entry_id>/edit/', edit_entry, name='edit_entry'),
    # path('<int:project_id>/edit/', edit_project, name='edit_project'),
    # path('delete_untracked_entry/<int:entry_id>/', delete_untracked_entry, name='delete_untracked_entry'),
    # path('track_entry/<int:entry_id>/', track_entry, name='track_entry'),
    # # API
]
