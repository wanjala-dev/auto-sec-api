# Import Python

import logging
from datetime import datetime

# Import Django
from django.utils import timezone

from components.team.application.facades.notification_facade import send_task_assignment_notification

logger = logging.getLogger(__name__)

# Import Django Rest Framework
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from components.project.application.service import ProjectService
from components.team.application.providers.team_context_provider import TeamContextProvider

# Import Facades
from components.workspace.application.facades.workspace_facade import (
    user_is_workspace_admin_or_owner,
    user_is_workspace_member,
)
from components.workspace.application.providers.board_view_mutation_provider import BoardViewMutationProvider
from components.workspace.application.providers.board_view_query_provider import BoardViewQueryProvider
from components.workspace.application.providers.column_query_provider import ColumnQueryProvider
from components.workspace.application.providers.time_tracking_provider import TimeTrackingProvider

# Module-level service instance for project operations
_project_service = ProjectService()

# Import Serializers
from components.project.application.facades.serializer_facade import (
    BoardViewSerializer,
    ColumnSerializer,
    ProjectGetSerializer,
    ProjectMilestoneSerializer,
    ProjectSerializer,
    ProjectUpdateSerializer,
    TaskCommentSerializer,
    TaskSerializer,
    WorkflowStatusLaneSerializer,
)


def _get_team_serializer():
    from components.team.mappers.rest.team_serializers import TeamSerializer

    return TeamSerializer


# Import permissions
from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.workspace.api.permissions import IsOrgOwnerOrMember
from components.workspace.api.workspace_permissions import (
    IsOwnerOrAdminOrStaffOrReadOnly,
)

# Task time-tracking timers are a Pro-tier feature.
_TIME_TRACKING_FLAG_KEY = "feature.time_tracking"


_team_context_port = TeamContextProvider.build_team_context_port()


def _resolve_active_team(request):
    """Resolve the requesting user's active team with membership validation.

    Replaces the repeated: UserProfile.objects.get() → Team.objects.get() → _require_team_member() pattern.
    """
    from components.project.domain.errors import TeamMembershipRequiredError

    try:
        return _team_context_port.resolve_active_team(
            actor_id=request.user.id,
            is_staff=getattr(request.user, "is_staff", False),
            is_superuser=getattr(request.user, "is_superuser", False),
        )
    except TeamMembershipRequiredError:
        raise PermissionDenied("You must be a member of this team.")


def _require_workspace_member(request, workspace):
    if not user_is_workspace_member(request.user, workspace):
        raise PermissionDenied("You must belong to the organization to perform this action.")


def _require_team_member(request, team):
    # Workspace admins/owners can interact with any team in their workspace
    # (including the seeded Agents team where the only "member" is the AI
    # user). Per ADR 0002 this branches on WorkspaceMembership.role, never
    # persona.
    if user_is_workspace_admin_or_owner(request.user, team.workspace):
        return
    if not team.members.filter(id=request.user.id).exists():
        raise PermissionDenied("You must be a member of this team.")


def _require_self(request, user_id):
    if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
        return
    if str(request.user.id) != str(user_id):
        raise PermissionDenied("You do not have permission to access this resource.")


class ProjectsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "user-projects"

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def post(self, request, *args, **kwargs):
        """Create a project — delegates to CreateProjectUseCase."""
        from components.project.domain.errors import (
            BudgetRequiredError,
            ProjectLimitExceededError,
            TaskValidationError,
            TeamMembershipRequiredError,
            TeamNotFoundError,
        )

        title = request.data.get("title")
        team_id = request.data.get("team")

        if not team_id:
            return Response({"success": False, "message": "Team is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response(
                {"success": False, "message": "Error occurred while adding project!"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = _project_service.create_project(
                title=title,
                team_id=str(team_id),
                user_id=str(request.user.id),
                workspace_id=request.data.get("workspace_id"),
                create_dedicated_budget=request.data.get("create_dedicated_budget", False),
            )
        except TeamNotFoundError:
            return Response({"success": False, "message": "Team not found."}, status=status.HTTP_404_NOT_FOUND)
        except TeamMembershipRequiredError:
            raise PermissionDenied("You must be a member of this team.")
        except (TaskValidationError, ProjectLimitExceededError, BudgetRequiredError) as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from components.project.mappers.rest.project_serializers import ProjectGetSerializer

        serializer = ProjectGetSerializer(result.project, context={"request": request})
        return Response(
            {
                "success": True,
                "message": "The project was added!",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request, *args, **kwargs):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )
        from components.project.mappers.rest.project_serializers import (
            project_get_serializer_for_version,
        )

        # Version-select the project read serializer. Under v1 the embedded
        # budget / budget-estimate money becomes C1 objects; v0 stays byte-
        # identical. ``request.version`` is ``'v0'`` for the unversioned alias.
        project_get_serializer = project_get_serializer_for_version(request.version)

        try:
            repo = get_project_repository_provider().get_repository()
            workspace = kwargs.get("workspace_id") or kwargs.get("workspace")  # Get workspace from URL
            team = kwargs.get("team")  # Get team from URL
            uuid = kwargs.get("uuid")  # Get user UUID from URL if needed

            if workspace and team:
                try:
                    workspace_obj = repo.get_workspace_by_id(workspace)
                except Exception:
                    return Response(
                        {"success": False, "message": "Workspace not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                _require_workspace_member(request, workspace_obj)
                try:
                    team_obj = repo.get_team_by_id(team, workspace_id=workspace, status="active")
                except Exception:
                    return Response(
                        {"success": False, "message": "Team not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                filtered_projects = repo.list_projects_for_workspace_and_team(workspace, team)
                serializer = project_get_serializer(filtered_projects, many=True, context={"request": request})

                return Response(
                    {
                        "success": True,
                        "status_code": status.HTTP_200_OK,
                        "message": "Projects for the provided workspace and team fetched successfully",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            elif workspace and uuid:
                _require_self(request, uuid)
                try:
                    workspace_obj = repo.get_workspace_by_id(workspace)
                except Exception:
                    return Response(
                        {"success": False, "message": "Workspace not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                _require_workspace_member(request, workspace_obj)
                workspace_projects = repo.list_projects_for_workspace(workspace)
                serializer = project_get_serializer(workspace_projects, many=True, context={"request": request})

                return Response(
                    {
                        "success": True,
                        "status_code": status.HTTP_200_OK,
                        "message": "Projects for the provided workspace fetched successfully",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            elif workspace:
                try:
                    workspace_obj = repo.get_workspace_by_id(workspace)
                except Exception:
                    return Response(
                        {"success": False, "message": "Workspace not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                _require_workspace_member(request, workspace_obj)
                workspace_projects = repo.list_projects_for_workspace(workspace)
                serializer = project_get_serializer(workspace_projects, many=True, context={"request": request})

                return Response(
                    {
                        "success": True,
                        "status_code": status.HTTP_200_OK,
                        "message": "Projects for the provided workspace fetched successfully",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            elif team:
                try:
                    team_obj = repo.get_team_by_id(team, status="active")
                except Exception:
                    return Response(
                        {"success": False, "message": "Team not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                _require_team_member(request, team_obj)
                team_projects = repo.list_projects_for_team(team)
                serializer = project_get_serializer(team_projects, many=True, context={"request": request})

                return Response(
                    {
                        "success": True,
                        "status_code": status.HTTP_200_OK,
                        "message": "Projects for the provided team fetched successfully",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            elif uuid:
                _require_self(request, uuid)
                active_team = _resolve_active_team(request)

                # Fetch all projects that belong to the user's active team
                user_projects = repo.list_projects_for_team_by_team_object(active_team)
                serializer = project_get_serializer(user_projects, many=True, context={"request": request})

                return Response(
                    {
                        "success": True,
                        "status_code": status.HTTP_200_OK,
                        "message": "Projects for the provided user fetched successfully",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            else:
                return Response(
                    {"success": False, "message": "Workspace, team, or user context is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


class ProjectView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "user-project"

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def get(self, request, project_id=None, uuid=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        if uuid:
            _require_self(request, uuid)
        team = _resolve_active_team(request)
        team_serializer = _get_team_serializer()(team, context={"request": request})

        repo = get_project_repository_provider().get_repository()
        try:
            project = repo.get_project_by_id(project_id)
        except Exception:
            return Response({"status": "error", "message": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        if project.team_id != team.id:
            return Response(
                {"status": "error", "message": "Project does not belong to your team"}, status=status.HTTP_403_FORBIDDEN
            )

        _require_workspace_member(request, project.workspace)
        project_serializer = ProjectSerializer(project, context={"request": request})

        tasks_todo = repo.list_tasks_for_project(project_id, status=Task.TODO)
        tasks_done = repo.list_tasks_for_project(project_id, status=Task.DONE)

        if uuid and project_id:
            status_code = status.HTTP_200_OK
            response = {
                "success": "true",
                "status code": status_code,
                "message": "Project found!",
                "data": {
                    "Project": project_serializer.data,
                    "Team": team_serializer.data,
                    "tasks_todo": tasks_todo,
                    "tasks_done": tasks_done,
                },
            }
            return Response(response, status=status_code)
        else:
            return Response({"status": "error", "message": "Error occured"}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, *args, **kwargs):
        """Create a task in a column — delegates to CreateTaskUseCase."""
        from components.project.application.ports.create_task_port import CreateTaskCommand
        from components.project.domain.errors import (
            ColumnNotFoundError,
            TaskLimitExceededError,
            TaskValidationError,
            TeamMembershipRequiredError,
        )

        title = request.data.get("title")
        column_id = request.data.get("column")

        if not column_id:
            return Response(
                {"error": "Column ID is required to post a task."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not title:
            return Response(
                {"status": "error", "message": "Error occurred while adding task!"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional planning fields (the task-creation wizard) — previously
        # settable only post-creation via PATCH. All optional and validated
        # in the adapter, so every existing title+column caller is untouched.
        assigned_to_raw = request.data.get("assigned_to")
        assigned_to_ids = (
            [str(uid) for uid in assigned_to_raw if uid] if isinstance(assigned_to_raw, (list, tuple)) else None
        )

        try:
            command = CreateTaskCommand(
                title=title,
                column_id=str(column_id),
                user_id=str(request.user.id),
                project_id=request.data.get("project_id"),
                grant_id=request.data.get("grant_id"),
                workspace_id=request.data.get("workspace_id"),
                description=str(request.data.get("description") or ""),
                due_date=request.data.get("due_date"),
                priority=request.data.get("priority"),
                assigned_to_ids=assigned_to_ids,
            )
            result = _project_service.create_task(command=command)
        except (ColumnNotFoundError, TaskValidationError, TaskLimitExceededError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except TeamMembershipRequiredError:
            raise PermissionDenied("You must be a member of this team.")

        return Response(
            {
                "success": True,
                "message": "The task was added!",
                "task": {
                    "pk": result.task_id,
                    "team": result.team_id,
                    "workspace_id": result.workspace_id,
                    "created_by": result.created_by,
                    "updated_at": result.updated_at,
                    "title": result.title,
                    "created_at": result.created_at,
                    "project": result.project_id,
                    "grant": result.grant_id,
                    "status": result.status,
                    "column": result.column_id,
                    "order": result.order,
                    "description": result.description,
                    "due_date": result.due_date,
                    "priority": result.priority,
                    "assigned_to_ids": result.assigned_to_ids,
                },
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    get=extend_schema(operation_id="project_detail_retrieve"),
    post=extend_schema(operation_id="project_detail_create"),
)
class ProjectDetailView(ProjectView):
    """Project detail view for unique schema operation IDs."""

    name = "user-project-detail"


class ProjectPatchView(APIView):
    """
    View to handle PATCH requests for updating a Project,
    returning the updated project using ProjectGetSerializer.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, project_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            # 1. Get the Project Instance
            repo = get_project_repository_provider().get_repository()
            try:
                project = repo.get_project_by_id(project_id)
            except Exception:
                return Response({"success": False, "message": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

            _require_workspace_member(request, project.workspace)
            _require_team_member(request, project.team)

            # 2. Serialize and Validate Data (using ProjectSerializer for PATCH)
            serializer = ProjectSerializer(project, data=request.data, partial=True, context={"request": request})

            if serializer.is_valid():
                serializer.save()

                # 3. Serialize the updated object using ProjectGetSerializer
                get_serializer = ProjectGetSerializer(project, context={"request": request})
                return Response({"success": True, "data": get_serializer.data}, status=status.HTTP_200_OK)
            else:
                return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


class TaskDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "user-tasks"

    def get(self, request, project_id=None, uuid=None, task_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        if uuid:
            _require_self(request, uuid)
        team = _resolve_active_team(request)
        team_serializer = _get_team_serializer()(team, context={"request": request})

        repo = get_project_repository_provider().get_repository()
        try:
            project = repo.get_project_by_id(project_id)
            if project.team_id != team.id:
                return Response(
                    {"status": "error", "message": "Project does not belong to your team"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            project_serializer = ProjectSerializer(project, context={"request": request})

            task = repo.get_task_by_id(task_id)
            if task.team_id != team.id:
                return Response(
                    {"status": "error", "message": "Task does not belong to your team"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except Exception:
            return Response({"status": "error", "message": "Resource not found"}, status=status.HTTP_404_NOT_FOUND)

        _require_workspace_member(request, task.workspace)
        task_serializer = TaskSerializer(task, context={"request": request})

        if uuid and project_id:
            status_code = status.HTTP_200_OK
            response = {
                "success": "true",
                "status code": status_code,
                "message": "Project found!",
                "data": {
                    #'project': project_serializer.data,
                    #'team':  team_serializer.data,
                    "task": task_serializer.data,
                    #'today':  datetime.today(),
                },
            }
            return Response(response, status=status_code)
        else:
            return Response({"status": "error", "message": "Error occured"}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, project_id=None, uuid=None, task_id=None, *args, **kwargs):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        data = request.data

        try:
            if uuid:
                _require_self(request, uuid)
            team = _resolve_active_team(request)
            team_serializer = _get_team_serializer()(team, context={"request": request})

            repo = get_project_repository_provider().get_repository()
            try:
                project = repo.get_project_by_id(project_id)
                if project.team_id != team.id:
                    return Response(
                        {"status": "error", "message": "Project does not belong to your team"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                project_serializer = ProjectSerializer(project, context={"request": request})

                task = repo.get_task_by_id(task_id)
                if task.team_id != team.id:
                    return Response(
                        {"status": "error", "message": "Task does not belong to your team"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except Exception:
                return Response({"status": "error", "message": "Resource not found"}, status=status.HTTP_404_NOT_FOUND)

            _require_workspace_member(request, task.workspace)
            task_serializer = TaskSerializer(task, context={"request": request})

            hours = int(data.get("hours", 0))
            minutes = int(data.get("minutes", 0))
            date_str = data.get("date")
            minutes_total = (hours * 60) + minutes
            date = "%s %s" % (date_str, datetime.now().time().strftime("%H:%M:%S"))
            workspace = task.workspace

            entry = repo.create_project_entry(
                workspace=workspace,
                team=team,
                project=project,
                task=task,
                minutes=minutes_total,
                created_by=request.user,
                created_at=date,
                is_tracked=True,
            )

            status_code = status.HTTP_200_OK
            response = {
                "success": True,
                "status code": status_code,
                "data": {
                    "project": project_serializer.data,
                    "team": team_serializer.data,
                    "task": task_serializer.data,
                    "today": datetime.today(),
                },
            }
            return Response(response, status=status_code)

        except (KeyError, ValueError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, uuid=None, task_id=None):
        """Update a task — delegates to UpdateTaskUseCase."""
        if uuid:
            _require_self(request, uuid)

        from components.project.application.ports.update_task_port import UpdateTaskCommand
        from components.project.domain.errors import (
            TaskNotFoundError,
            TaskValidationError,
            TeamMembershipRequiredError,
            WorkspaceMembershipRequiredError,
        )

        try:
            command = UpdateTaskCommand(
                task_id=str(task_id),
                user_id=str(request.user.id),
                data=request.data,
                http_request=request,
            )
            result = _project_service.update_task(command=command)
        except TaskNotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except WorkspaceMembershipRequiredError:
            raise PermissionDenied("You must belong to the organization to perform this action.")
        except TeamMembershipRequiredError:
            return Response(
                {"success": False, "message": "You must be a member of the task's team to update it."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except TaskValidationError as exc:
            return Response({"success": False, "errors": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"success": True, "task": result.task}, status=status.HTTP_200_OK)


class TaskUpdateView(TaskDetailView):
    """Patch + delete task operations by task ID (the kanban card callout).

    ``delete`` lives HERE, not on the base ``TaskDetailView``, so it only
    applies to the ``tasks/<task_id>/`` route — the base view's other routes
    (``task/<project_id>/<uuid>/<task_id>`` etc.) do NOT gain a DELETE verb.
    """

    http_method_names = ["patch", "delete"]

    def delete(self, request, uuid=None, task_id=None, **kwargs):
        """Soft-delete a task INTO the recycle bin (never a hard delete).

        A board card is a Task; deleting it must tombstone it into the
        recycle bin — it drops off the active board (board queries exclude
        ``status=ARCHIVED``), appears in the recycle-bin listing, and is
        restorable via the existing recycle-bin restore flow. This reuses the
        recycle_bin application surface (``get_recycle_bin_service().trash``) —
        the same path ``content``'s draft delete uses — instead of hand-rolling
        tombstoning. Idempotent: an already-trashed task returns 204.
        """
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )
        from components.recycle_bin.application.commands.trash_command import TrashCommand
        from components.recycle_bin.application.providers.recycle_bin_provider import (
            get_recycle_bin_service,
        )
        from components.shared_kernel.domain.errors import ConflictError
        from infrastructure.persistence.project.models import Task

        if uuid:
            _require_self(request, uuid)

        repo = get_project_repository_provider().get_repository()
        try:
            task = repo.get_task_by_id(task_id)
        except Task.DoesNotExist:
            # Only a genuinely missing task is a 404 — a real DB fault must
            # surface, not be masked as "not found" (logging.md §7).
            return Response({"success": False, "message": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        # Only someone who can mutate the task/board may trash it — mirror the
        # existing task-mutation permission (workspace member + team member,
        # admins/owners bypass team per ADR 0002).
        _require_workspace_member(request, task.workspace)
        _require_team_member(request, task.team)

        try:
            get_recycle_bin_service().trash(
                TrashCommand(
                    workspace_id=task.workspace_id,
                    entity_type="task",
                    entity_id=str(task.id),
                    deleted_by=request.user.id,
                    reason=str(request.data.get("reason") or ""),
                )
            )
        except ConflictError:
            # Already in the bin (race with a concurrent delete) — the
            # outcome the caller asked for already holds.
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)


class MoveTaskToBoardView(APIView):
    """POST /project/tasks/<task_id>/move-board/

    Move a single task to a DIFFERENT board — atomically reassigning its
    team + project + target column. Unlike batch-move (which only touches the
    ``column`` FK), this keeps ``team`` / ``project`` consistent when a card
    crosses boards. The destination board is derived from the target column, so
    the three FKs can never disagree.

    Body: { "column": <target_column_id>, "order": <int, optional> }
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "task-move-board"

    def post(self, request, task_id=None, *args, **kwargs):
        from components.project.application.ports.move_task_to_board_port import (
            MoveTaskToBoardCommand,
        )
        from components.project.domain.errors import (
            TaskNotFoundError,
            TaskValidationError,
            TeamMembershipRequiredError,
            WorkspaceMembershipRequiredError,
        )

        target_column_id = request.data.get("column") or request.data.get("target_column")
        if not target_column_id:
            return Response(
                {"success": False, "message": "A target 'column' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order_raw = request.data.get("order")
        order = None
        if order_raw is not None:
            try:
                order = int(order_raw)
            except (TypeError, ValueError):
                return Response(
                    {"success": False, "message": "'order' must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            command = MoveTaskToBoardCommand(
                task_id=str(task_id),
                target_column_id=str(target_column_id),
                user_id=str(request.user.id),
                order=order,
            )
            result = _project_service.move_task_to_board(command=command)
        except TaskNotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except WorkspaceMembershipRequiredError:
            raise PermissionDenied("You must belong to the organization to perform this action.")
        except TeamMembershipRequiredError:
            return Response(
                {"success": False, "message": "You must be a member of the destination board's team."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except TaskValidationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "success": True,
                "message": "Task moved to the destination board.",
                "data": {
                    "task_id": result.task_id,
                    "team_id": result.team_id,
                    "project_id": result.project_id,
                    "column_id": result.column_id,
                    "order": result.order,
                },
            },
            status=status.HTTP_200_OK,
        )


class BatchMoveTasksView(APIView):
    """POST /project/tasks/batch-move/

    Move multiple tasks to new columns/positions in a single request.
    Accepts: { "moves": [{ "task_id": 1, "column": 5, "order": 0 }, ...] }
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        from components.project.application.ports.batch_move_tasks_port import (
            BatchMoveTasksCommand,
            TaskMove,
        )
        from components.project.domain.errors import (
            TaskNotFoundError,
            TeamMembershipRequiredError,
            WorkspaceMembershipRequiredError,
        )

        moves_data = request.data.get("moves")
        if not moves_data or not isinstance(moves_data, list):
            return Response(
                {"success": False, "message": "A non-empty 'moves' list is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(moves_data) > 100:
            return Response(
                {"success": False, "message": "Maximum 100 moves per batch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_moves = []
        for item in moves_data:
            task_id = item.get("task_id")
            column_id = item.get("column")
            if not task_id or not column_id:
                return Response(
                    {"success": False, "message": "Each move requires 'task_id' and 'column'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            task_moves.append(
                TaskMove(
                    task_id=str(task_id),
                    column_id=str(column_id),
                    order=item.get("order"),
                )
            )

        try:
            command = BatchMoveTasksCommand(moves=task_moves, user_id=str(request.user.id))
            result = _project_service.batch_move_tasks(command=command)
        except TaskNotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except WorkspaceMembershipRequiredError:
            raise PermissionDenied("You must belong to the organization to perform this action.")
        except TeamMembershipRequiredError:
            return Response(
                {"success": False, "message": "You must be a member of the task's team."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {"success": True, "updated_count": result.updated_count},
            status=status.HTTP_200_OK,
        )


def _emit_task_assigned(*, task, assignee_id: str, actor_id: str) -> None:
    """Fire ``task_assigned`` workflow event for one newly-assigned user."""
    from components.workflow.application.providers.workflow_dispatcher_provider import (
        get_workflow_dispatcher_provider,
    )

    emit_workflow_event = get_workflow_dispatcher_provider().emit_workflow_event

    emit_workflow_event(
        workspace_id=str(task.workspace_id),
        source_type="task",
        trigger_type="task_assigned",
        payload={
            "workspace_id": str(task.workspace_id),
            "user_id": actor_id,
            "task_id": str(task.id),
            "project_id": str(task.project_id) if task.project_id else None,
            "team_id": str(task.team_id),
            "assignee_id": assignee_id,
            "task_source_type": task.source_type or "",
            "target_type": "group",
            "target_id": str(task.workspace_id),
        },
        source_id=str(task.id),
        idempotency_key=f"task_assigned:{task.id}:{assignee_id}",
    )


class AssignUsersToTaskView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, task_id):
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        db_transaction = _django_orm.transaction

        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            task = repo.get_task_by_id(task_id)
        except Exception:
            return Response({"error": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        _require_workspace_member(request, task.workspace)
        _require_team_member(request, task.team)
        user_ids = request.data.get("user_ids", [])
        assigned_users = []

        try:
            users_to_assign = repo.get_users_to_assign(user_ids)
        except ValueError:
            return Response({"error": "Invalid user IDs provided."}, status=status.HTTP_400_BAD_REQUEST)

        team_member_ids = set(task.team.members.values_list("id", flat=True))
        invalid_ids = [str(user.id) for user in users_to_assign if user.id not in team_member_ids]
        if invalid_ids:
            return Response(
                {"error": "Users must belong to the task's team.", "invalid_user_ids": invalid_ids},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_ids = set(task.assigned_to.values_list("id", flat=True))
        actor_id = str(request.user.id) if request.user.is_authenticated else ""
        for user in users_to_assign:
            if user.id in existing_ids:
                continue
            # Emission inside per-user atomic so add + on_commit are paired;
            # SMTP stays outside so a mail failure doesn't roll back the FK row.
            with db_transaction.atomic():
                task.assigned_to.add(user)
                assignee_id = str(user.id)
                db_transaction.on_commit(
                    lambda t=task, aid=assignee_id, act=actor_id: _emit_task_assigned(
                        task=t,
                        assignee_id=aid,
                        actor_id=act,
                    )
                )
            assigned_users.append(user)
            if task.team:
                send_task_assignment_notification(request, task, user, task.team)

        # Pass the request context here
        serializer = TaskSerializer(task, context={"request": request})
        return Response({"success": True, "task": serializer.data}, status=status.HTTP_200_OK)


class TaskCommentMixin:
    """Shared helpers for task comment views."""

    serializer_class = TaskCommentSerializer
    _task = None

    def get_task(self):
        if self._task is None:
            from components.project.application.providers.project_repository_provider import (
                get_project_repository_provider,
            )

            task_id = self.kwargs.get("task_id")
            repo = get_project_repository_provider().get_repository()
            try:
                self._task = repo.get_task_by_id(task_id)
            except Exception:
                from rest_framework.exceptions import NotFound

                raise NotFound("Task not found.")
            _require_workspace_member(self.request, self._task.workspace)
        return self._task

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["task"] = self.get_task()
        return context

    def get_base_queryset(self):
        from infrastructure.persistence.project.models import TaskComment

        return (
            TaskComment.objects.filter(task=self.get_task())
            .select_related("author", "author__profile", "task")
            .prefetch_related(
                "likes",
                "dislikes",
                "replies",
                "replies__author",
                "replies__author__profile",
                "replies__likes",
                "replies__dislikes",
            )
        )


class TaskCommentListCreateView(TaskCommentMixin, generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "task-comment-list"
    pagination_class = None

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        return self.get_base_queryset().filter(parent__isnull=True)

    def perform_create(self, serializer):
        task = self.get_task()
        parent = serializer.validated_data.get("parent")
        if parent and parent.task_id != task.id:
            raise ValidationError("Parent comment must belong to the same task.")
        serializer.save(author=self.request.user, task=task)


class TaskCommentDetailView(TaskCommentMixin, generics.RetrieveUpdateDestroyAPIView):
    lookup_url_kwarg = "comment_id"
    name = "task-comment-detail"
    permission_classes = (permissions.IsAuthenticated,)

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsOwnerOrAdminOrStaffOrReadOnly()]

    def get_queryset(self):
        return self.get_base_queryset()


class StartTimerView(APIView):
    permission_classes = (IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _TIME_TRACKING_FLAG_KEY

    def post(self, request, *args, **kwargs):
        workspace_id = request.data.get("workspace_id")
        if not workspace_id:
            return Response({"error": "Workspace ID is required."}, status=400)

        try:
            use_case = TimeTrackingProvider.build_start_timer()
            result = use_case.execute(
                user=request.user,
                workspace_id=workspace_id,
                task_id=request.data.get("task_id"),
                project_id=request.data.get("project_id"),
                now=timezone.now(),
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=403)

        return Response(
            {
                "success": True,
                "entry_id": result.entry_id,
                "total_tracked_minutes": result.total_tracked_minutes,
            }
        )


class StopTimerView(APIView):
    permission_classes = (IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _TIME_TRACKING_FLAG_KEY

    def post(self, request, *args, **kwargs):
        try:
            use_case = TimeTrackingProvider.build_stop_timer()
            result = use_case.execute(
                user=request.user,
                task_id=request.data.get("task_id"),
                project_id=request.data.get("project_id"),
                now=timezone.now(),
            )
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"success": False, "message": str(exc)}, status=404)

        return Response(
            {
                "success": True,
                "entry_id": result.entry_id,
                "total_tracked_minutes": int(result.total_tracked_minutes),
            }
        )


class DiscardTimerView(APIView):
    permission_classes = (IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _TIME_TRACKING_FLAG_KEY

    def post(self, request, *args, **kwargs):
        try:
            use_case = TimeTrackingProvider.build_discard_timer()
            result = use_case.execute(
                user=request.user,
                task_id=request.data.get("task_id"),
                project_id=request.data.get("project_id"),
            )
        except ValueError as exc:
            return Response({"success": False, "message": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"success": False, "message": str(exc)}, status=404)

        return Response(
            {
                "success": True,
                "message": "Timer discarded successfully.",
                "total_tracked_minutes": int(result.total_tracked_minutes),
            }
        )


#
# def api_discard_timer(request):
#     entries = Entry.objects.filter(team_id=request.user.userprofile.active_team_id, created_by=request.user, is_tracked=False).order_by('-created_at')
#
#     if entries:
#         entry = entries.first()
#         entry.delete()
#
#     return JsonResponse({'success': True})
#


class TasksView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "all-user-tasks"

    def get(self, request, project_id=None, uuid=None, team_id=None, workspace_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()

            if team_id and workspace_id:
                try:
                    team = repo.get_team_by_id(team_id, status="active")
                except Exception:
                    return Response(
                        {"status": "error", "message": "Team not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                if str(team.workspace_id) != str(workspace_id):
                    return Response(
                        {"status": "error", "message": "Workspace does not match the selected team."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                _require_team_member(request, team)
                tasks = repo.list_tasks_for_team_and_workspace(team_id, workspace_id)

                # Prepare response data
                tasks_data = []
                for task in tasks:
                    task_data = TaskSerializer(task, context={"request": request}).data
                    tasks_data.append(task_data)

                status_code = status.HTTP_200_OK
                response = {"success": True, "status code": status_code, "data": {"tasks": tasks_data}}
                return Response(response, status=status_code)

            elif uuid and project_id:
                _require_self(request, uuid)
                team = _resolve_active_team(request)
                try:
                    project = repo.get_project_by_id(project_id)
                    if project.team_id != team.id:
                        return Response(
                            {"status": "error", "message": "Project does not belong to your team"},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                except Exception:
                    return Response(
                        {"status": "error", "message": "Project not found"}, status=status.HTTP_404_NOT_FOUND
                    )

                tasks = []
                for task in project.tasks.all():  # Fetch tasks related to the project
                    task_data = TaskSerializer(task, context={"request": request}).data
                    tasks.append(task_data)

                status_code = status.HTTP_200_OK
                response = {
                    "success": True,
                    "status code": status_code,
                    "data": {
                        "team": _get_team_serializer()(team, context={"request": request}).data,
                        "project": ProjectSerializer(project, context={"request": request}).data,
                        "tasks": tasks,
                    },
                }
                return Response(response, status=status_code)

            else:
                return Response(
                    {"status": "error", "message": "Invalid parameters or missing data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            return Response(
                {"status": "error", "message": f"Error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


class TasksForEntityView(APIView):
    """List tasks associated with a given grant."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, grant_id=None):
        from infrastructure.persistence.project.models import Task

        # assigned_to__profile: the task serializer renders each assignee's
        # profile (avatar) — without the nested prefetch every assignee row
        # lazy-loads its profile. Mirrors the main board path in
        # project_repository.
        queryset = Task.objects.select_related(
            "team",
            "workspace",
            "project",
            "column",
            "created_by",
            "grant",
        ).prefetch_related("assigned_to__profile", "assigned_to")
        if grant_id:
            queryset = queryset.filter(grant_id=grant_id)
        else:
            return Response(
                {"status": "error", "message": "grant_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tasks = list(queryset.order_by("order", "created_at"))
        data = [TaskSerializer(task, context={"request": request}).data for task in tasks]
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "data": {"tasks": data},
            },
            status=status.HTTP_200_OK,
        )


class AssignedTasksView(APIView):
    """List tasks assigned to the current user in a workspace, across all teams.

    Powers the frontend "My Work" page. Read-only. The caller only ever sees
    their OWN assigned tasks (``assigned_to`` scoped to ``request.user``),
    spanning every team in the workspace. Mirrors ``ProjectsView`` — same
    ``IsAuthenticated`` permission, same repository-mediated read, and the
    same response envelope so the frontend unwraps the list from
    ``response.data.data``.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "tasks-assigned-to-me"

    def get(self, request, workspace_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        if not workspace_id:
            return Response(
                {"success": False, "message": "Workspace is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repo = get_project_repository_provider().get_repository()
        try:
            workspace_obj = repo.get_workspace_by_id(workspace_id)
        except Exception:
            return Response(
                {"success": False, "message": "Workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        _require_workspace_member(request, workspace_obj)

        tasks = repo.list_tasks_assigned_to_user(workspace_id, request.user.id)
        serializer = TaskSerializer(tasks, many=True, context={"request": request})

        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "message": "Tasks assigned to the current user fetched successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class ColumnsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "columns"

    def get(self, request, column_id=None, project_id=None, team_id=None, workspace_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )
        from components.project.domain.errors import (
            ValidationError as DomainValidationError,
        )
        from components.workspace.application.queries.column_query import FetchColumnsQuery

        try:
            query = ColumnQueryProvider.build_query()
            filter_req = FetchColumnsQuery.parse_params(
                column_id=column_id,
                project_id=project_id,
                team_id=team_id,
                workspace_id=workspace_id,
                user_assigned=request.query_params.get("user_assigned", None),
                user=request.user,
                # Per-column task window (always applied; clamped server-side).
                # Lanes report `tasks_total` / `tasks_has_more`; the remainder
                # pages through GET /project/columns/<id>/tasks/.
                tasks_limit=request.query_params.get("tasks_limit", None),
            )
            columns = query.execute(request=filter_req)

            serializer = ColumnSerializer(columns, many=True, context={"request": request})
            filtered_data = [item for item in serializer.data if item not in (None, {})]

            return Response(
                {
                    "success": True,
                    "status_code": status.HTTP_200_OK,
                    "message": "Columns fetched successfully",
                    "data": filtered_data,
                },
                status=status.HTTP_200_OK,
            )
        except (NotFoundError, DomainValidationError) as exc:
            # Team/workspace mismatch or missing resources — return empty data
            # instead of an error so the frontend renders the empty state.
            return Response(
                {"success": True, "status_code": status.HTTP_200_OK, "message": str(exc), "data": []},
                status=status.HTTP_200_OK,
            )
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)

    def put(self, request, column_id=None, *args, **kwargs):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            if not column_id:
                return Response(
                    {"success": False, "message": "Column ID is required."}, status=status.HTTP_400_BAD_REQUEST
                )

            repo = get_project_repository_provider().get_repository()
            try:
                column = repo.get_column_by_id(column_id)
            except Exception:
                return Response({"success": False, "message": "Column not found."}, status=status.HTTP_404_NOT_FOUND)

            _require_workspace_member(request, column.workspace)
            _require_team_member(request, column.team)

            # Validate and update the column with provided data using the serializer
            # serializer = ColumnSerializer(column, data=request.data, partial=True)
            serializer = ColumnSerializer(
                column, data=request.data, partial=True, context={"request": request}
            )  # Pass context here

            if serializer.is_valid():
                from components.shared_kernel.application.providers.django_orm_provider import (
                    get_django_orm_provider as _get_django_orm_provider,
                )

                _django_orm = _get_django_orm_provider()
                transaction = _django_orm.transaction

                with transaction.atomic():
                    serializer.save()

                    # If the column is being soft deleted, also update the tasks
                    if request.data.get("is_deleted", False):
                        repo.archive_tasks_for_column(column_id)

                return Response(
                    {"success": True, "message": "Column updated successfully", "data": serializer.data},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"success": False, "message": "Invalid data", "errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    # POST method to create a new column
    def post(self, request, *args, **kwargs):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        data = request.data
        team_id = data.get("team")
        workspace_id = data.get("workspace")
        if not team_id or not workspace_id:
            return Response(
                {"success": False, "message": "Team and workspace are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repo = get_project_repository_provider().get_repository()
        try:
            team = repo.get_team_by_id(team_id, status="active")
            workspace = repo.get_workspace_by_id(workspace_id)
        except Exception:
            return Response(
                {"success": False, "message": "Team or workspace not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if str(team.workspace_id) != str(workspace.id):
            return Response(
                {"success": False, "message": "Team does not belong to this organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _require_team_member(request, team)

        project = None
        project_id = data.get("project")
        if project_id:
            try:
                project = repo.get_project_by_id(project_id)
                if project.team_id != team.id or project.workspace_id != workspace.id:
                    return Response(
                        {"success": False, "message": "Project does not belong to the specified team or workspace."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except Exception:
                return Response(
                    {"success": False, "message": "Project not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        serializer = ColumnSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            serializer.save(team=team, workspace=workspace, created_by=request.user, project=project)
            return Response(
                {"success": True, "message": "Column created successfully", "data": serializer.data},
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {"success": False, "message": "Invalid data", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, column_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            if not column_id:
                return Response(
                    {"success": False, "message": "Column ID is required."}, status=status.HTTP_400_BAD_REQUEST
                )

            repo = get_project_repository_provider().get_repository()
            try:
                column = repo.get_column_by_id(column_id)
            except Exception:
                return Response({"success": False, "message": "Column not found."}, status=status.HTTP_404_NOT_FOUND)

            _require_workspace_member(request, column.workspace)
            _require_team_member(request, column.team)
            column.is_deleted = True
            column.save()

            return Response(
                {"success": True, "message": "Column marked as deleted successfully"}, status=status.HTTP_204_NO_CONTENT
            )

        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema_view(
    get=extend_schema(operation_id="project_columns_detail_retrieve"),
    post=extend_schema(operation_id="project_columns_detail_create"),
    put=extend_schema(operation_id="project_columns_detail_update"),
    delete=extend_schema(operation_id="project_columns_detail_destroy"),
)
class ColumnDetailView(ColumnsView):
    """Column detail view for unique schema operation IDs."""

    name = "column-detail"


class ColumnTasksView(APIView):
    """One lane's task window, in board order — the board's "load more" read.

    GET /project/columns/<column_id>/tasks/?offset=<n>&limit=<n>

    The board endpoints window every lane (``tasks_limit`` per column); this
    endpoint pages the remainder of a single lane with the same ordering and
    eager-loading contract, so consecutive windows never skip or duplicate
    cards. Offset/limit (not page numbers) because lanes are appended to
    incrementally from a moving client-side length.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "column-tasks"

    def get(self, request, column_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )

        try:
            query = ColumnQueryProvider.build_column_tasks_query()
            page = query.execute(
                column_id=column_id,
                user=request.user,
                offset=request.query_params.get("offset", 0),
                limit=request.query_params.get("limit", None),
            )
            serializer = TaskSerializer(page.tasks, many=True, context={"request": request})
            return Response(
                {
                    "success": True,
                    "status_code": status.HTTP_200_OK,
                    "message": "Column tasks fetched successfully",
                    "data": serializer.data,
                    "meta": {
                        "total": page.total,
                        "offset": page.offset,
                        "limit": page.limit,
                        "has_more": page.has_more,
                    },
                },
                status=status.HTTP_200_OK,
            )
        except NotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)


# Boards-as-views read API (ADR 0030 P2a). Additive + flag-gated: OFF (the
# seeded default) keeps today's column board authoritative and these
# endpoints answer 403 via RequiresFeatureFlag — the repo's established
# flag-gate convention (same class gates the timer endpoints above).
_BOARDS_AS_VIEWS_FLAG_KEY = "feature.boards_as_views"


class TeamBoardViewsView(APIView):
    """GET /project/teams/<team_id>/views/ — the team's saved board views.

    The views bar's read (ADR 0030 Decision §2): every board is a saved
    ``BoardView`` over the team's one status vocabulary. System views come
    from the P1 backfill (the unfiltered team board + one per project board);
    user-saved views (#74) become later non-system rows on the same read.
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _BOARDS_AS_VIEWS_FLAG_KEY
    name = "team-board-views"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Evaluate the flag against the TEAM's workspace, not the user's
        active workspace (the resource-scoped resolver contract on
        ``RequiresFeatureFlag`` — see the AI-writing draft precedent)."""
        from components.team.application.providers.team_models_provider import get_team_models_provider

        Team = get_team_models_provider().Team
        ws_id = Team.objects.filter(pk=self.kwargs.get("team_id")).values_list("workspace_id", flat=True).first()
        return str(ws_id) if ws_id else None

    def get(self, request, team_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )

        try:
            views = BoardViewQueryProvider.build_team_views_query().execute(team_id=team_id, user=request.user)
        except NotFoundError as exc:
            # Unknown team OR a team outside the requester's workspaces — the
            # same 404 either way, so ids never leak across the tenant boundary.
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = BoardViewSerializer(views, many=True, context={"request": request})
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "message": "Board views fetched successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, team_id=None):
        """POST /project/teams/<team_id>/views/ — save a personal view (task #74).

        Body: ``name`` (required), ``filter`` (closed vocabulary, validated by
        the model), ``group_by`` (optional; only "status" exists). The row is
        appended after the team's existing views. ``created_by`` is ALWAYS the
        authenticated user and ``is_system`` always False — never read from
        the body (mass-assignment protection).
        """
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )
        from components.project.domain.errors import (
            ValidationError as DomainValidationError,
        )
        from components.workspace.application.commands.board_view_commands import CreateBoardViewCommand

        command = CreateBoardViewCommand(
            team_id=team_id,
            name=request.data.get("name"),
            filter=request.data.get("filter") if request.data.get("filter") is not None else {},
            group_by=request.data.get("group_by") if request.data.get("group_by") is not None else "status",
        )
        try:
            view = BoardViewMutationProvider.build_create_view_use_case().execute(command=command, user=request.user)
        except NotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except DomainValidationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BoardViewSerializer(view, context={"request": request})
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_201_CREATED,
                "message": "View saved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class BoardViewDetailView(APIView):
    """PATCH/DELETE /project/views/<view_id>/ — manage a personal saved view (task #74).

    Own views only: another member's personal view answers the same 404 the
    list implies (it was never visible); workspace admins/owners may manage
    any personal view (the established admin bypass). System views are
    IMMUTABLE — 403 with an explicit message. Same flag gate + resource-scoped
    flag resolution as the P2a reads.
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _BOARDS_AS_VIEWS_FLAG_KEY
    name = "view-detail"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Evaluate the flag against the VIEW's workspace (resource-scoped)."""
        from components.project.application.providers.project_models_provider import get_project_models_provider

        BoardView = get_project_models_provider().BoardView
        ws_id = BoardView.objects.filter(pk=self.kwargs.get("view_id")).values_list("workspace_id", flat=True).first()
        return str(ws_id) if ws_id else None

    def patch(self, request, view_id=None):
        """Rename / re-filter / reorder — partial; only provided keys change."""
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )
        from components.project.domain.errors import (
            ValidationError as DomainValidationError,
        )
        from components.workspace.application.commands.board_view_commands import UpdateBoardViewCommand

        command = UpdateBoardViewCommand(
            view_id=view_id,
            name=request.data.get("name") if "name" in request.data else None,
            filter=request.data.get("filter") if "filter" in request.data else None,
            group_by=request.data.get("group_by") if "group_by" in request.data else None,
            order=request.data.get("order") if "order" in request.data else None,
        )
        try:
            view = BoardViewMutationProvider.build_update_view_use_case().execute(command=command, user=request.user)
        except NotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except DomainValidationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BoardViewSerializer(view, context={"request": request})
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "message": "View updated successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, view_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )

        try:
            BoardViewMutationProvider.build_delete_view_use_case().execute(view_id=view_id, user=request.user)
        except NotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {"success": True, "message": "View deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )


class ViewBoardView(APIView):
    """GET /project/views/<view_id>/board/ — one view's board.

    Lanes come from the team's ``WorkflowStatus`` rows (ordered, with
    category); membership is ``task.workflow_status`` restricted by the
    view's closed-vocabulary ``filter``. Windowing is identical to the
    column board (``tasks_limit`` per lane + ``tasks_total`` /
    ``tasks_has_more``; the remainder pages through the lane-tasks
    endpoint) so the HUD swap is a lane-source change, not a re-plumb.
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _BOARDS_AS_VIEWS_FLAG_KEY
    name = "view-board"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Evaluate the flag against the VIEW's workspace (resource-scoped)."""
        from components.project.application.providers.project_models_provider import get_project_models_provider

        BoardView = get_project_models_provider().BoardView
        ws_id = BoardView.objects.filter(pk=self.kwargs.get("view_id")).values_list("workspace_id", flat=True).first()
        return str(ws_id) if ws_id else None

    def get(self, request, view_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )

        try:
            board = BoardViewQueryProvider.build_view_board_query().execute(
                view_id=view_id,
                user=request.user,
                # Per-lane task window (always applied; clamped server-side to
                # the SAME bounds as the column board).
                tasks_limit=request.query_params.get("tasks_limit", None),
            )
        except NotFoundError as exc:
            # Unknown view OR another workspace's view — identical 404 (never
            # 403): a cross-tenant probe must not learn the view exists.
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        context = {"request": request}
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "message": "View board fetched successfully",
                "data": {
                    "view": BoardViewSerializer(board.view, context=context).data,
                    "lanes": WorkflowStatusLaneSerializer(board.statuses, many=True, context=context).data,
                },
            },
            status=status.HTTP_200_OK,
        )


class ViewLaneTasksView(APIView):
    """GET /project/views/<view_id>/lanes/<status_id>/tasks/?offset=&limit=

    One status lane's task window in board order, with the view's filter
    applied — the view board's "load more" read, mirroring
    ``ColumnTasksView`` (same ordering + eager-loading contract, same
    ``meta`` shape) so consecutive windows never skip or duplicate cards.
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _BOARDS_AS_VIEWS_FLAG_KEY
    name = "view-lane-tasks"

    def get_feature_flag_workspace_id(self, request) -> str | None:
        """Evaluate the flag against the VIEW's workspace (resource-scoped)."""
        from components.project.application.providers.project_models_provider import get_project_models_provider

        BoardView = get_project_models_provider().BoardView
        ws_id = BoardView.objects.filter(pk=self.kwargs.get("view_id")).values_list("workspace_id", flat=True).first()
        return str(ws_id) if ws_id else None

    def get(self, request, view_id=None, status_id=None):
        from components.project.domain.errors import (
            AuthorizationError,
            NotFoundError,
        )

        try:
            page = BoardViewQueryProvider.build_view_lane_tasks_query().execute(
                view_id=view_id,
                status_id=status_id,
                user=request.user,
                offset=request.query_params.get("offset", 0),
                limit=request.query_params.get("limit", None),
            )
        except NotFoundError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except AuthorizationError as exc:
            return Response({"success": False, "message": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        serializer = TaskSerializer(page.tasks, many=True, context={"request": request})
        return Response(
            {
                "success": True,
                "status_code": status.HTTP_200_OK,
                "message": "View lane tasks fetched successfully",
                "data": serializer.data,
                "meta": {
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                    "has_more": page.has_more,
                },
            },
            status=status.HTTP_200_OK,
        )


class ColumnReorderView(APIView):
    """Atomically update the `order` field for a batch of columns.

    Accepts POST with body: { "updates": [{"id": <int>, "order": <int>}, ...] }
    All columns must belong to the same team+workspace and the caller must be
    a member of both. Either all updates succeed or none do.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "column-reorder"

    def post(self, request, *args, **kwargs):
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        transaction = _django_orm.transaction
        from infrastructure.persistence.project.models import Column

        updates = request.data.get("updates")
        if not isinstance(updates, list) or not updates:
            return Response(
                {"success": False, "message": "updates must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cleaned = []
        for entry in updates:
            if not isinstance(entry, dict):
                return Response(
                    {"success": False, "message": "Each update must be an object."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            column_id = entry.get("id") or entry.get("pk") or entry.get("column_id")
            order = entry.get("order")
            try:
                column_id_int = int(column_id)
                order_int = int(order)
            except (TypeError, ValueError):
                return Response(
                    {"success": False, "message": "id and order must be integers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cleaned.append((column_id_int, order_int))

        ids = [cid for cid, _ in cleaned]
        columns = list(Column.objects.filter(pk__in=ids, is_deleted=False))
        if len(columns) != len(set(ids)):
            return Response(
                {"success": False, "message": "One or more columns not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # All columns in the batch must share the same team and workspace.
        team_ids = {c.team_id for c in columns}
        workspace_ids = {str(c.workspace_id) for c in columns}
        if len(team_ids) != 1 or len(workspace_ids) != 1:
            return Response(
                {
                    "success": False,
                    "message": "All columns must belong to the same team and workspace.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        sample = columns[0]
        _require_workspace_member(request, sample.workspace)
        _require_team_member(request, sample.team)

        order_map = {cid: order for cid, order in cleaned}

        with transaction.atomic():
            for column in columns:
                new_order = order_map.get(column.pk)
                if new_order is None or column.order == new_order:
                    continue
                column.order = new_order
                column.save(update_fields=["order", "updated_at"])

        refreshed = Column.objects.filter(pk__in=ids, is_deleted=False).order_by("order")
        serializer = ColumnSerializer(refreshed, many=True, context={"request": request})
        return Response(
            {
                "success": True,
                "message": "Column order updated.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class ProjectUpdatesView(APIView):
    """Create, retrieve, update, and delete project updates."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "project_updates"

    def get(self, request, update_id=None, project_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()

            if update_id:
                try:
                    project_update = repo.get_project_update_by_id(update_id)
                except Exception:
                    return Response(
                        {"success": False, "message": "Project Update not found."}, status=status.HTTP_404_NOT_FOUND
                    )
                _require_workspace_member(request, project_update.workspace)
                serializer = ProjectUpdateSerializer(project_update)
                return Response({"success": True, "data": serializer.data})
            elif project_id:
                try:
                    project = repo.get_project_by_id(project_id)
                except Exception:
                    return Response(
                        {"success": False, "message": "Project not found."}, status=status.HTTP_404_NOT_FOUND
                    )
                _require_workspace_member(request, project.workspace)
                project_updates = repo.list_project_updates_for_project(project_id)
                serializer = ProjectUpdateSerializer(project_updates, many=True)
                return Response({"success": True, "data": serializer.data})
            else:
                return Response(
                    {"success": False, "message": "Project context is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    def post(self, request):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        project_id = request.data.get("Project") or request.data.get("project")
        if not project_id:
            return Response(
                {"success": False, "message": "Project is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        repo = get_project_repository_provider().get_repository()
        try:
            project = repo.get_project_by_id(project_id)
        except Exception:
            return Response({"success": False, "message": "Project not found."}, status=status.HTTP_404_NOT_FOUND)
        _require_workspace_member(request, project.workspace)

        serializer = ProjectUpdateSerializer(data=request.data)
        if serializer.is_valid():
            project_update = serializer.save(author=request.user, workspace=project.workspace, Project=project)

            # Emit project_update_posted workflow event
            try:
                from components.workflow.application.providers.workflow_dispatcher_provider import (
                    get_workflow_dispatcher_provider,
                )

                emit_workflow_event = get_workflow_dispatcher_provider().emit_workflow_event

                emit_workflow_event(
                    workspace_id=str(project.workspace_id),
                    source_type="project",
                    trigger_type="project_update_posted",
                    payload={
                        "workspace_id": str(project.workspace_id),
                        "project_id": str(project.id),
                        "update_id": str(project_update.id),
                        "target_type": "contact",
                        "target_id": str(request.user.id),
                        "contact_id": str(request.user.id),
                        "author_id": str(request.user.id),
                    },
                    source_id=str(project.id),
                    idempotency_key=f"project_update_posted:{project.workspace_id}:{project_update.id}",
                )
            except Exception:
                logger.exception("Failed to emit project_update_posted workflow event")

            return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, update_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            try:
                project_update = repo.get_project_update_by_id(update_id)
            except Exception:
                return Response(
                    {"success": False, "message": "Project Update not found."}, status=status.HTTP_404_NOT_FOUND
                )
            _require_workspace_member(request, project_update.workspace)
            serializer = ProjectUpdateSerializer(project_update, data=request.data)
            if serializer.is_valid():
                serializer.save(
                    author=project_update.author,
                    workspace=project_update.workspace,
                    Project=project_update.Project,
                )
                return Response({"success": True, "data": serializer.data})
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    def patch(self, request, update_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            try:
                project_update = repo.get_project_update_by_id(update_id)
            except Exception:
                return Response(
                    {"success": False, "message": "Project Update not found."}, status=status.HTTP_404_NOT_FOUND
                )
            _require_workspace_member(request, project_update.workspace)
            serializer = ProjectUpdateSerializer(project_update, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save(
                    author=project_update.author,
                    workspace=project_update.workspace,
                    Project=project_update.Project,
                )
                return Response({"success": True, "data": serializer.data})
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    def delete(self, request, update_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            try:
                project_update = repo.get_project_update_by_id(update_id)
            except Exception:
                return Response(
                    {"success": False, "message": "Project Update not found."}, status=status.HTTP_404_NOT_FOUND
                )
            _require_workspace_member(request, project_update.workspace)
            project_update.delete()
            return Response({"success": True, "message": "Project Update deleted."}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema_view(
    get=extend_schema(operation_id="project_updates_detail_retrieve"),
    post=extend_schema(operation_id="project_updates_detail_create"),
    put=extend_schema(operation_id="project_updates_detail_update"),
    patch=extend_schema(operation_id="project_updates_detail_partial_update"),
    delete=extend_schema(operation_id="project_updates_detail_destroy"),
)
class ProjectUpdateDetailView(ProjectUpdatesView):
    """Project update detail view for unique schema operation IDs."""

    name = "project_update_detail"


class MilestonesView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "milestones"

    def get(self, request, milestone_id=None, project_id=None):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()

            if milestone_id:
                try:
                    milestone = repo.get_milestone_by_id(milestone_id)
                except Exception:
                    return Response(
                        {"success": False, "message": "Milestone not found."}, status=status.HTTP_404_NOT_FOUND
                    )
                projects = milestone.projects.select_related("workspace")
                if not any(user_is_workspace_member(request.user, project.workspace) for project in projects):
                    return Response({"success": False, "message": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
                serializer = ProjectMilestoneSerializer(milestone)
                return Response({"success": True, "data": serializer.data})
            elif project_id:
                try:
                    project = repo.get_project_by_id(project_id)
                except Exception:
                    return Response(
                        {"success": False, "message": "Project not found."}, status=status.HTTP_404_NOT_FOUND
                    )
                _require_workspace_member(request, project.workspace)
                milestones = repo.list_milestones_for_project(project_id)
                serializer = ProjectMilestoneSerializer(milestones, many=True)
                return Response({"success": True, "data": serializer.data})
            else:
                return Response(
                    {"success": False, "message": "Project context is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    def post(self, request):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        project_id = request.data.get("project_id")
        if not project_id:
            return Response(
                {"success": False, "message": "Project is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        repo = get_project_repository_provider().get_repository()
        try:
            project = repo.get_project_by_id(project_id)
        except Exception:
            return Response({"success": False, "message": "Project not found."}, status=status.HTTP_404_NOT_FOUND)
        _require_workspace_member(request, project.workspace)

        serializer = ProjectMilestoneSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            milestone = serializer.save(creator=request.user)
            project.milestones.add(milestone)
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, milestone_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            try:
                milestone = repo.get_milestone_by_id(milestone_id)
            except Exception:
                return Response({"success": False, "message": "Milestone not found."}, status=status.HTTP_404_NOT_FOUND)
            projects = milestone.projects.select_related("workspace")
            if not any(user_is_workspace_member(request.user, project.workspace) for project in projects):
                return Response({"success": False, "message": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
            serializer = ProjectMilestoneSerializer(milestone, data=request.data)
            if serializer.is_valid():
                serializer.save()

                # Emit project_milestone_done workflow event
                try:
                    from components.workflow.application.providers.workflow_dispatcher_provider import (
                        get_workflow_dispatcher_provider,
                    )

                    emit_workflow_event = get_workflow_dispatcher_provider().emit_workflow_event

                    project = projects.first()
                    if project and project.workspace_id:
                        emit_workflow_event(
                            workspace_id=str(project.workspace_id),
                            source_type="project",
                            trigger_type="project_milestone_done",
                            payload={
                                "workspace_id": str(project.workspace_id),
                                "project_id": str(project.id),
                                "milestone_id": str(milestone.id),
                                "milestone_name": milestone.name,
                                "target_type": "contact",
                                "target_id": str(request.user.id),
                                "contact_id": str(request.user.id),
                            },
                            source_id=str(project.id),
                            idempotency_key=f"project_milestone_done:{project.workspace_id}:{milestone.id}",
                        )
                except Exception:
                    logger.exception("Failed to emit project_milestone_done workflow event")

                return Response({"success": True, "data": serializer.data})
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )

    def delete(self, request, milestone_id):
        from components.project.application.providers.project_repository_provider import (
            get_project_repository_provider,
        )

        try:
            repo = get_project_repository_provider().get_repository()
            try:
                milestone = repo.get_milestone_by_id(milestone_id)
            except Exception:
                return Response({"success": False, "message": "Milestone not found."}, status=status.HTTP_404_NOT_FOUND)
            projects = milestone.projects.select_related("workspace")
            if not any(user_is_workspace_member(request.user, project.workspace) for project in projects):
                return Response({"success": False, "message": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
            milestone.delete()
            return Response({"success": True, "message": "Milestone deleted."}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response(
                {"success": False, "message": f"An error occurred: {e!s}"}, status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema_view(
    get=extend_schema(operation_id="project_milestones_detail_retrieve"),
    post=extend_schema(operation_id="project_milestones_detail_create"),
    put=extend_schema(operation_id="project_milestones_detail_update"),
    delete=extend_schema(operation_id="project_milestones_detail_destroy"),
)
class MilestoneDetailView(MilestonesView):
    """Project milestone detail view for unique schema operation IDs."""

    name = "milestone_detail"
