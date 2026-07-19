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
        description=(
            "Get details about an organization/workspace. Use for ANY "
            "'tell me about this workspace', 'workspace overview', "
            "'who are we', 'what does this organization do', 'workspace "
            "profile' style question. Input: organization name or ID "
            "(optional, defaults to current workspace). Output: name, "
            "story, sector, team size, member counts, creation date."
        ),
    )
    def get_organization_info(self, input_str: str) -> str:
        return workspace_tools.get_organization_info(self, input_str)

    @tool(
        name="update_organization",
        description="Update organization information. Input: organization_id (optional, defaults to current workspace), field, new_value. Output: updated organization info.",
    )
    def update_organization(self, input_str: str) -> str:
        return workspace_tools.update_organization(self, input_str)

    @tool(
        name="manage_organization_team",
        description="Manage organization team members. Input: organization_id (optional, defaults to current workspace), action (add/remove), user_id. Output: team management result.",
    )
    def manage_organization_team(self, input_str: str) -> str:
        return workspace_tools.manage_organization_team(self, input_str)

    @tool(
        name="get_organization_analytics",
        description=(
            "Get organization-level analytics and statistics. Use for "
            "ANY 'how is the organization doing', 'workspace analytics', "
            "'show me our metrics', 'how are we performing as an org' "
            "style question. Input: organization_id (optional, defaults "
            "to current workspace). Output: aggregate analytics data."
        ),
    )
    def get_organization_analytics(self, input_str: str) -> str:
        return workspace_tools.get_organization_analytics(self, input_str)

    @tool(
        name="manage_organization_categories",
        description="Manage organization categories and subcategories. Input: organization_id (optional, defaults to current workspace), categories, subcategories. Output: category management result.",
    )
    def manage_organization_categories(self, input_str: str) -> str:
        return workspace_tools.manage_organization_categories(self, input_str)

    @tool(
        name="manage_organization_tags",
        description="Manage organization tags. Input: organization_id (optional, defaults to current workspace), tags (add/remove). Output: tag management result.",
    )
    def manage_organization_tags(self, input_str: str) -> str:
        return workspace_tools.manage_organization_tags(self, input_str)

    @tool(
        name="get_organization_followers",
        description=(
            "List the workspace's followers and engagement stats. Use "
            "for ANY 'who follows us', 'list our followers', 'how many "
            "followers do we have', 'show me followers' style question. "
            "Input: organization_id (optional). Output: followers list "
            "and aggregate stats."
        ),
    )
    def get_organization_followers(self, input_str: str) -> str:
        return workspace_tools.get_organization_followers(self, input_str)

    @tool(
        name="manage_organization_privacy",
        description="Manage organization privacy settings. Input: organization_id (optional, defaults to current workspace), privacy_level (public/private). Output: privacy update result.",
    )
    def manage_organization_privacy(self, input_str: str) -> str:
        return workspace_tools.manage_organization_privacy(self, input_str)

    @tool(
        name="get_organization_operations",
        description="Get organization operations and activities. Input: organization_id (optional, defaults to current workspace). Output: operations list.",
    )
    def get_organization_operations(self, input_str: str) -> str:
        return workspace_tools.get_organization_operations(self, input_str)

    @tool(
        name="manage_organization_operations",
        description="Manage organization operations. Input: organization_id (optional, defaults to current workspace), operations (add/remove). Output: operations management result.",
    )
    def manage_organization_operations(self, input_str: str) -> str:
        return workspace_tools.manage_organization_operations(self, input_str)

    @tool(
        name="check_organization_permissions",
        description="Check if user can access organization data. Input: user_id, organization_id (optional, defaults to current workspace). Output: permission status.",
    )
    def check_organization_permissions(self, input_str: str) -> str:
        return workspace_tools.check_organization_permissions(self, input_str)

