"""Workspace/Organization Management Agent — migrated to the decorator
framework (ADR 0003).

Note: This agent intentionally does NOT mix in `WorkspaceContextMixin`.
The agent is itself the authority on workspace/organization concepts and
already exposes organization-level introspection tools
(`get_organization_info`, `get_organization_analytics`, etc.). Mixing in
`WorkspaceContextMixin` would add `whoami` / `get_workspace_info` tools
that overlap conceptually with this agent's own surface. Keeping the tool
set byte-identical to the legacy `_setup_tools` registration preserves
DB-stored `custom_profile.tool_whitelist` parity.

Keyword-routing short-circuits (`_maybe_handle_direct`,
`_DIRECT_OVERVIEW_KEYWORDS`) were removed in the Deep Agent Unification
track — the deep planner + `retrieve_workspace_context` tool replace
them with honest grounded answers.
"""
from components.agents.application.policies.tool_spec import Scope
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    workspace_agent as workspace_tools,
)


@register_agent("workspace_agent", aliases=("workspaces", "organization"))
class WorkspaceAgent(BaseAgent):
    """Agent for managing organizations/workspaces"""

    profile = {
        "name": "Workspace Agent",
        # User-facing summary — rendered in the agents directory UI.
        # Disambiguation against task_agent is enforced in the planner
        # system prompt (PER-TASK SPECIALIST ROUTING table), NOT here,
        # so this copy stays readable for end users.
        "summary": (
            "Manages your organization profile, categories, tags, privacy "
            "settings, member invites and roles, followers, and "
            "workspace-level analytics and reports."
        ),
        "capabilities": [
            "Create, update, and describe organizations/workspaces",
            "Manage organization categories, tags, and operations",
            "Invite, remove, or change roles for workspace members",
            "Surface followers, analytics, and engagement data",
            "Check user permissions against an organization",
        ],
        "sample_prompts": [
            "Give me an overview of this workspace",
            "List our followers",
            "Update the workspace's privacy setting to public",
        ],
    }

    # ── Tool name strings MUST stay byte-identical to the legacy
    # `_setup_tools` registrations so DB-stored
    # `custom_profile.tool_whitelist` configs keep working. ──

    @tool(
        name="create_organization",
        description="Create a new organization/workspace. Input: organization data (name, story, category, privacy). Output: organization details.",
    )
    def create_organization(self, input_str: str) -> str:
        return workspace_tools.create_organization(self, input_str)

    @tool(
        name="get_organization_info",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Get details about an organization/workspace. Use for ANY "
            "'tell me about this workspace', 'workspace overview', "
            "'who are we', 'what does this organization do', 'workspace "
            "profile' style question. Takes no input — it always "
            "describes the current workspace. Output: name, "
            "story, sector, team size, member counts, creation date."
        ),
    )
    def get_organization_info(self, input_str: str) -> str:
        return workspace_tools.get_organization_info(self, input_str)

    @tool(
        name="update_organization",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Update a field on the CURRENT workspace's organization "
            "profile. Input: field, new_value. Output: updated "
            "organization info. The organization is always the current "
            "workspace and cannot be chosen."
        ),
    )
    def update_organization(self, input_str: str) -> str:
        return workspace_tools.update_organization(self, input_str)

    @tool(
        name="manage_organization_team",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Manage the CURRENT workspace's team members. Input: action "
            "(add/remove), user_id. Output: team management result. The "
            "organization is always the current workspace and cannot be "
            "chosen."
        ),
    )
    def manage_organization_team(self, input_str: str) -> str:
        return workspace_tools.manage_organization_team(self, input_str)

    @tool(
        name="get_organization_analytics",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Get organization-level analytics and statistics. Use for "
            "ANY 'how is the organization doing', 'workspace analytics', "
            "'show me our metrics', 'how are we performing as an org' "
            "style question. Takes no input — the analytics are always "
            "for the current workspace. Output: aggregate analytics data."
        ),
    )
    def get_organization_analytics(self, input_str: str) -> str:
        return workspace_tools.get_organization_analytics(self, input_str)

    @tool(
        name="manage_organization_categories",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Manage the CURRENT workspace's categories and "
            "subcategories. Input: categories, subcategories. Output: "
            "category management result. The organization is always the "
            "current workspace and cannot be chosen."
        ),
    )
    def manage_organization_categories(self, input_str: str) -> str:
        return workspace_tools.manage_organization_categories(self, input_str)

    @tool(
        name="manage_organization_tags",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Manage the CURRENT workspace's tags. Input: action "
            "(add/remove), tags. Output: tag management result. The "
            "organization is always the current workspace and cannot be "
            "chosen."
        ),
    )
    def manage_organization_tags(self, input_str: str) -> str:
        return workspace_tools.manage_organization_tags(self, input_str)

    @tool(
        name="get_organization_followers",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "List the workspace's followers and engagement stats. Use "
            "for ANY 'who follows us', 'list our followers', 'how many "
            "followers do we have', 'show me followers' style question. "
            "Takes no input — the followers are always the current "
            "workspace's. Output: followers list and aggregate stats."
        ),
    )
    def get_organization_followers(self, input_str: str) -> str:
        return workspace_tools.get_organization_followers(self, input_str)

    @tool(
        name="manage_organization_privacy",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Manage the CURRENT workspace's privacy setting. Input: "
            "privacy_level (public/private). Output: privacy update "
            "result. The organization is always the current workspace "
            "and cannot be chosen."
        ),
    )
    def manage_organization_privacy(self, input_str: str) -> str:
        return workspace_tools.manage_organization_privacy(self, input_str)

    @tool(
        name="get_organization_operations",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Get the CURRENT workspace's operations and activities. "
            "Takes no input. Output: operations list."
        ),
    )
    def get_organization_operations(self, input_str: str) -> str:
        return workspace_tools.get_organization_operations(self, input_str)

    @tool(
        name="manage_organization_operations",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Manage the CURRENT workspace's operations. Input: action "
            "(add/remove), operations. Output: operations management "
            "result. The organization is always the current workspace "
            "and cannot be chosen."
        ),
    )
    def manage_organization_operations(self, input_str: str) -> str:
        return workspace_tools.manage_organization_operations(self, input_str)

    @tool(
        name="check_organization_permissions",
        scope=Scope.WORKSPACE_BOUND,
        description=(
            "Check whether a user can access the CURRENT workspace's "
            "organization data. Input: user_id. Output: permission "
            "status. The organization is always the current workspace "
            "and cannot be chosen."
        ),
    )
    def check_organization_permissions(self, input_str: str) -> str:
        return workspace_tools.check_organization_permissions(self, input_str)

