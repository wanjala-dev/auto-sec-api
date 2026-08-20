"""Project Management Agent — migrated to the decorator framework (ADR 0003)."""

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.policies.tool_spec import Failure, Provenance, Scope
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    project_agent as project_tools,
)


@register_agent("project_agent", aliases=("project", "project_management"))
class ProjectAgent(WorkspaceContextMixin, BaseAgent):
    """Agent for managing projects, tasks, and team coordination."""

    profile = {
        "name": "Project Agent",
        "summary": (
            "Plans, tracks, and reports on workspace projects. Handles "
            "project creation (including AI-assisted planning), task and "
            "milestone management, team assignments, budgets, timelines, "
            "risks, and analytics."
        ),
        "capabilities": [
            "Create projects directly or from a natural-language prompt",
            "Create projects with an auto-generated task and estimate plan",
            "List, inspect, and report on projects in the workspace",
            "Track actual project spend over custom time windows",
            "Update project status, progress, and team assignments",
            "Create and update project tasks and milestones",
            "Surface project timelines, analytics, and risks/issues",
            "Manage project budgets and generate status/budget/timeline reports",
            "Check user permissions for project data access",
        ],
        "sample_prompts": [
            "Create a project called 'Spring Literacy Drive' with a budget of 5000",
            "How much have we spent on the Literacy Drive project this quarter?",
            "List all active projects",
            "Plan and create a project for onboarding new sponsors",
            "Show the timeline for project 42",
            "Add a high-severity risk to the Literacy Drive project",
        ],
    }

    # ── Tool name strings MUST stay byte-identical to the legacy
    # `_setup_tools` registrations so DB-stored
    # `custom_profile.tool_whitelist` configs keep working. ──

    # ── ADR 0031 Phase 4 — the declaration ────────────────────────────────
    # Every tool below carries `scope` / `risk` / `provenance` /
    # `failure_mode`. Two of those values deserve a word, because they look
    # like placeholders and are not:
    #
    # `provenance=Provenance.NONE` — not one tool here posts to the board,
    #   including the ones that write. That is today's behaviour stated
    #   exactly; it deliberately does not pre-empt ADR 0031 OQ3 (whether
    #   "every AI action posts to the board" binds every state-changing tool).
    #
    # `failure_mode=Failure.INTERNAL` — this is the honest declaration for a
    #   body that still catches `Exception` and returns a string: the tool
    #   CANNOT tell you why it failed, and `INTERNAL` is what "we don't know"
    #   is called. It is not a default nobody chose — it is the F4 remediation
    #   list, restated where the tool is defined. A body converted to narrow
    #   excepts + `ToolResult` declares a real reason instead, and
    #   `tests/architecture/test_tool_blanket_exception.py` names every one
    #   still outstanding.
    # ──────────────────────────────────────────────────────────────────────

    @tool(
        name="create_project",
        description=(
            "Create a new project on a team. Use for 'create a project', "
            "'start a new project', 'open a project for X' style requests. "
            'Input JSON: {"name" (or "title"), "team_id" (required), '
            '"confirm": true}. Requires confirm=true. Output: the created '
            "project's id."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def create_project(self, input_str: str) -> str:
        return project_tools.create_project(self, input_str)

    @tool(
        name="list_projects",
        description=(
            "List projects in the current workspace. Use for ANY 'list "
            "our projects', 'how many projects do we have', 'show me "
            "active projects', 'what projects are running' style "
            'question. Optional input as JSON: {"status"?, "limit"?}. '
            "Output: 'Projects (N): • Title  Status: ...  Budget: ...'."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def list_projects(self, input_str: str) -> str:
        return project_tools.list_projects(self, input_str)

    @tool(
        name="get_project_info",
        description=(
            "Fetch a project's details. Use for ANY 'tell me about "
            "project X', 'what's project X', 'project details for X' "
            "style question. Input: project name or ID. Output: title, "
            "status, priority, dates, team, lead, tasks, milestones."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def get_project_info(self, input_str: str) -> str:
        return project_tools.get_project_info(self, input_str)

    @tool(
        name="update_project",
        description=(
            "Update fields on an existing project. Pass only the fields "
            'you want changed. Input as JSON: {"project_id": uuid, '
            '"title"?, "description"?, "status"?, "priority"?, '
            '"start_date"? (YYYY-MM-DD or null), "end_date"? '
            '(YYYY-MM-DD or null), "resources"?, "lead_user_id"? '
            "(or null to unassign)}."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def update_project(self, input_str: str) -> str:
        return project_tools.update_project(self, input_str)

    @tool(
        name="assign_project_team",
        description="Assign team members to a project. Input: project_id, team_member_ids. Output: assignment details.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def assign_project_team(self, input_str: str) -> str:
        return project_tools.assign_project_team(self, input_str)

    @tool(
        name="create_project_task",
        description="Create a task within a project. Input: project_id, task_data (title, description, assignee_id, due_date). Output: task details.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def create_project_task(self, input_str: str) -> str:
        return project_tools.create_project_task(self, input_str)

    @tool(
        name="get_project_tasks",
        description=(
            "List tasks scoped to a single project. Use for ANY 'show "
            "me tasks for project X', 'project X tasks', 'list tasks "
            "in project Y' style question. Input: project_id + optional "
            "status_filter. For workspace-wide task lists use "
            "task_agent's list_workspace_tasks instead."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def get_project_tasks(self, input_str: str) -> str:
        return project_tools.get_project_tasks(self, input_str)

    # ── update_task_status REMOVED 2026-05-08 ──
    #
    # Canonical home is task_agent. Task status mutation is a
    # task-domain verb — project_agent's surface stays scoped to
    # project-level operations (milestones, risks, project budget,
    # team assignment). The planner routes "mark task X done" to
    # task_agent. See Pattern D test.

    @tool(
        name="get_project_timeline",
        description=(
            "Get a project's timeline and milestones. Use for ANY "
            "'project timeline', 'when does project X finish', 'show "
            "me project milestones', 'what's coming up on project Y' "
            "style question. Input: project_id. Output: timeline with "
            "milestones + deadlines."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def get_project_timeline(self, input_str: str) -> str:
        return project_tools.get_project_timeline(self, input_str)

    @tool(
        name="create_project_milestone",
        description="Create a project milestone. Input: project_id, milestone_data (name, due_date, description). Output: milestone details.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def create_project_milestone(self, input_str: str) -> str:
        return project_tools.create_project_milestone(self, input_str)

    @tool(
        name="update_project_milestone",
        description=(
            "Update a milestone attached to a project. Required: "
            "project_id (parent), milestone_id (integer). Optional: "
            "name, description, target_date (YYYY-MM-DD). Pass as JSON."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def update_project_milestone(self, input_str: str) -> str:
        return project_tools.update_project_milestone(self, input_str)

    @tool(
        name="delete_project_milestone",
        description=(
            "Remove a milestone from a project. Required: project_id, "
            "milestone_id. The milestone is detached AND deleted if no "
            "other project still owns it. Pass as JSON."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def delete_project_milestone(self, input_str: str) -> str:
        return project_tools.delete_project_milestone(self, input_str)

    @tool(
        name="get_project_analytics",
        description="Get project analytics and statistics. Input: project_id (optional), date_range (optional). Output: analytics data.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def get_project_analytics(self, input_str: str) -> str:
        return project_tools.get_project_analytics(self, input_str)

    @tool(
        name="generate_project_report",
        description=(
            "Generate a comprehensive report on a project. Use for ANY "
            "'project status report', 'project budget report', 'show "
            "me a project summary' style request. Input: project_id + "
            "report_type (status / budget / timeline)."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def generate_project_report(self, input_str: str) -> str:
        return project_tools.generate_project_report(self, input_str)

    @tool(
        name="manage_project_budget",
        description="Manage project budget and expenses. Input: project_id, budget_data (allocated_amount, spent_amount). Output: budget info.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.REVERSIBLE_WRITE,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def manage_project_budget(self, input_str: str) -> str:
        return project_tools.manage_project_budget(self, input_str)

    # ── add_project_risk + get_project_risks REMOVED 2026-05-08 ──
    #
    # Both tools imported and queried a ``Risk`` model that does not
    # exist anywhere in the codebase — they would crash with ImportError
    # the first time the LLM picked them. The synthesizer would then
    # paraphrase the failure into a fabricated answer (the exact 2026-
    # 05-08 hallucination shape). Registrations removed; underlying
    # functions stay as dead code (marked TODO) until a Risk model is
    # introduced. Until then there is no project-risk capability.

    @tool(
        name="check_project_permissions",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Check whether a user can access project data in the CURRENT "
            "workspace. Input: user_id, project_id (optional). Output: "
            "permission status. The workspace is always the current one "
            "and cannot be chosen."
        ),
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def check_project_permissions(self, input_str: str) -> str:
        return project_tools.check_project_permissions(self, input_str)
