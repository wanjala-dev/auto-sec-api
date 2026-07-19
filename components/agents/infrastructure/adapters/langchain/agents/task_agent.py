"""Task Management Agent — migrated to the decorator framework (ADR 0003)."""
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)


@register_agent("task_agent", aliases=("task", "task_management"))
class TaskAgent(WorkspaceContextMixin, BaseAgent):
    """Task Management Agent for handling project and task operations."""

    profile = {
        "name": "Task Agent",
        "summary": (
            "Creates, assigns, and tracks tasks across projects. Parses task "
            "requests, breaks down complex work into subtasks, routes work to "
            "team members, and reports on progress and due dates."
        ),
        "capabilities": [
            "Parse task details from natural-language requests",
            "Create tasks and break them into subtasks",
            "Assign tasks to team members and list assignees",
            "List team members, including those without tasks",
            "Report tasks by user, due date, and overall progress",
            "Update task status and verify permissions",
        ],
        "sample_prompts": [
            "Create a task to draft the quarterly report due Friday",
            "Who is assigned to the 'launch checklist' task?",
            "Which team members have no tasks assigned?",
            "Show me my tasks due today",
        ],
    }

    # ── Tool name strings MUST stay byte-identical to the legacy
    # `_setup_tools` registrations so DB-stored
    # `custom_profile.tool_whitelist` configs keep working. ──

    @tool(
        name="parse_task_request",
        description="Parse task details from user request (title, description, assignee, due date, priority)",
    )
    def parse_task_request(self, input_str: str) -> str:
        return task_tools.parse_task_request(self, input_str)

    @tool(
        name="create_task",
        description=(
            "Create a new task on a team's kanban board. Use for ANY "
            "'create a task', 'add a task', 'new task', 'I need to do "
            "X' style request. Input: title (required), description, "
            "assignee, project, due_date, column_title."
        ),
    )
    def create_task(self, input_str: str) -> str:
        return task_tools.create_task(self, input_str)

    @tool(
        name="break_down_task",
        description="Break down a complex task into subtasks",
    )
    def break_down_task(self, input_str: str) -> str:
        return task_tools.break_down_task(self, input_str)

    @tool(
        name="assign_task",
        description="Assign a task to a team member",
    )
    def assign_task(self, input_str: str) -> str:
        return task_tools.assign_task(self, input_str)

    @tool(
        name="get_task_assignment",
        description="Get current assignees for a specific task by ID or partial title",
    )
    def get_task_assignment(self, input_str: str) -> str:
        return task_tools.get_task_assignment(self, input_str)

    @tool(
        name="get_team_members",
        description="Get available team members for task assignment",
    )
    def get_team_members(self, input_str: str) -> str:
        return task_tools.get_team_members(self, input_str)

    @tool(
        name="get_members_without_tasks",
        description="List team members who currently have no tasks assigned (optionally scoped by team_id)",
    )
    def get_members_without_tasks(self, input_str: str) -> str:
        return task_tools.get_members_without_tasks(self, input_str)

    @tool(
        name="get_projects",
        description="Get available projects for task assignment",
    )
    def get_projects(self, input_str: str) -> str:
        return task_tools.get_projects(self, input_str)

    @tool(
        name="list_workspace_tasks",
        description=(
            "List tasks across the entire workspace (NOT user-scoped). Use this "
            "for ANY 'how many tasks', 'list our tasks', 'what's in todo', "
            "'show me tasks' style questions. Optional input as JSON: "
            "{\"status\": \"todo\"|\"done\"|\"archived\" or list, "
            "\"project_id\": uuid, \"priority\": \"low\"|\"medium\"|\"high\"|\"urgent\", "
            "\"limit\": int (default 50)}. Pass {} or empty for all active tasks. "
            "Output: 'Tasks (N total): • Title  Status: ...  Priority: ...  ...'."
        ),
    )
    def list_workspace_tasks(self, input_str: str) -> str:
        return task_tools.list_workspace_tasks(self, input_str)

    @tool(
        name="get_user_tasks",
        description="Get tasks assigned to a specific user (use get_task_assignment to see who owns a task). For workspace-wide task counts/lists, use list_workspace_tasks instead.",
    )
    def get_user_tasks(self, input_str: str) -> str:
        return task_tools.get_user_tasks(self, input_str)

    @tool(
        name="get_due_tasks",
        description=(
            "List tasks due on a specific date. Use for ANY 'what's "
            "due today', 'tasks due tomorrow', 'show me tasks due this "
            "week', 'what's overdue' style question. Input: optional "
            "user_id, optional date (defaults to today). Output: list "
            "of tasks due on that date."
        ),
    )
    def get_due_tasks(self, input_str: str) -> str:
        return task_tools.get_due_tasks(self, input_str)

    @tool(
        name="update_task_status",
        description=(
            "Change a task's status (todo / done / archived). Use for "
            "ANY 'mark task as done', 'mark X complete', 'reopen task', "
            "'set status to in progress' style request. Input as JSON: "
            "{\"task_id\": uuid, \"status\": \"todo\"|\"done\"|\"archived\"}."
        ),
    )
    def update_task_status(self, input_str: str) -> str:
        return task_tools.update_task_status(self, input_str)

    @tool(
        name="update_task_due_date",
        description=(
            "Update a task's due date. Input as JSON: "
            "{\"task_id\": uuid, \"due_date\": \"YYYY-MM-DD\" or "
            "\"YYYY-MM-DDTHH:MM:SS\" or null to clear}. "
            "Output: confirmation with the new due date."
        ),
    )
    def update_task_due_date(self, input_str: str) -> str:
        return task_tools.update_task_due_date(self, input_str)

    @tool(
        name="update_task_title",
        description=(
            "Rename a task. Input as JSON: {\"task_id\": uuid, "
            "\"title\": \"New title\"}. Title must be 1-255 chars. "
            "Output: 'Renamed task: \"old\" → \"new\"'."
        ),
    )
    def update_task_title(self, input_str: str) -> str:
        return task_tools.update_task_title(self, input_str)

    @tool(
        name="delete_task",
        description=(
            "Archive (soft-delete) a task. The Task model has no "
            "hard-delete; archived tasks are hidden from default "
            "list_workspace_tasks output but preserved for audit. "
            "Input as JSON: {\"task_id\": uuid}. Output: confirmation."
        ),
    )
    def delete_task(self, input_str: str) -> str:
        return task_tools.delete_task(self, input_str)

    @tool(
        name="add_task_comment",
        description=(
            "Add a comment to a task. Optionally reply to an existing "
            "comment by passing parent_comment_id. Input as JSON: "
            "{\"task_id\": uuid, \"comment\": \"...\", "
            "\"parent_comment_id\": uuid (optional)}. "
            "Output: confirmation with comment id."
        ),
    )
    def add_task_comment(self, input_str: str) -> str:
        return task_tools.add_task_comment(self, input_str)

    @tool(
        name="list_task_comments",
        description=(
            "List comments on a task, most recent first. Input as JSON: "
            "{\"task_id\": uuid, \"limit\": int (default 50)}. "
            "Output: 'Comments on \"<title>\" (N total): • <when> "
            "<author>  <body>'."
        ),
    )
    def list_task_comments(self, input_str: str) -> str:
        return task_tools.list_task_comments(self, input_str)

    @tool(
        name="start_task_timer",
        description=(
            "Start a time-tracking timer on a task. Use for ANY 'start "
            "the timer', 'begin tracking time', 'I'm working on X' "
            "style request. Input as JSON: {\"task_id\": uuid}. "
            "Calls the same StartTimerUseCase the kanban play button "
            "uses — running timer shows up on the task card."
        ),
    )
    def start_task_timer(self, input_str: str) -> str:
        return task_tools.start_task_timer(self, input_str)

    @tool(
        name="stop_task_timer",
        description=(
            "Stop the currently-running timer on a task and record the "
            "elapsed minutes. Use for ANY 'stop the timer', 'I'm done "
            "with X', 'pause tracking' style request. Input as JSON: "
            "{\"task_id\": uuid}. Returns the recorded minutes."
        ),
    )
    def stop_task_timer(self, input_str: str) -> str:
        return task_tools.stop_task_timer(self, input_str)

    @tool(
        name="get_task_timer_status",
        description=(
            "Report whether a task has a running timer plus total "
            "tracked minutes across all entries. Use for 'is the timer "
            "running on X', 'how much time have I tracked on X' style "
            "questions. Input as JSON: {\"task_id\": uuid}."
        ),
    )
    def get_task_timer_status(self, input_str: str) -> str:
        return task_tools.get_task_timer_status(self, input_str)

    @tool(
        name="get_task_progress",
        description=(
            "Get an aggregate progress summary across tasks. Use for "
            "ANY 'how is the team progressing', 'task progress', 'what "
            "percent of tasks are done', 'overall task completion' style "
            "question. Input: optional project_id to scope. Output: "
            "counts + completion percentage."
        ),
    )
    def get_task_progress(self, input_str: str) -> str:
        return task_tools.get_task_progress(self, input_str)

    @tool(
        name="check_task_permissions",
        description="Verify user has permission to perform task operations on the current workspace. Input: optional user_id. Output: permission status and reason.",
    )
    def check_task_permissions(self, input_str: str) -> str:
        # Underlying ``task_tools.check_permissions`` returns bool —
        # the StructuredTool surface expects a string. Wrap with a
        # user-readable response so the LLM can act on it.
        allowed = task_tools.check_permissions(self, input_str)
        return (
            "User has permission to perform task operations on this workspace."
            if allowed
            else "User does not have permission to perform task operations on this workspace."
        )

