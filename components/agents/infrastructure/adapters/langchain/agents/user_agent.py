"""User Agent — workspace member identity, profiles, and audit activity (ADR 0003).

Fills the identity-domain gap the registry has carried since launch: no
specialist owned "who is in this workspace", "what's Alice's role", or "what
has Bob done recently". Before this agent, those queries fell into the
``clarify`` bucket (or, before v4, into ``workspace_agent`` which lacks any
member-read tools and would thrash).

Tool surface (4 tools, all workspace-scoped):
* ``list_workspace_members`` — names + roles + statuses of active members
* ``search_workspace_members`` — substring search across this workspace only
* ``get_user_profile`` — single member by user_id or email
* ``list_user_activity`` — audit-log entries actor'd by a user
  (role-gated to owner/admin — surfaces what other users did)

Inherits ``whoami`` + ``get_workspace_info`` from ``WorkspaceContextMixin``.
"""

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.policies.tool_spec import Failure, Provenance, Scope
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    requires_role,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    user_agent as user_tools,
)
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)


@register_agent(
    "user_agent",
    aliases=("user", "users", "identity_agent", "identity", "members"),
)
class UserAgent(WorkspaceContextMixin, BaseAgent):
    """Agent for workspace member identity, profiles, and per-user audit activity."""

    profile = {
        "name": "User Agent",
        "summary": (
            "Answers questions about people in this workspace — who the "
            "active members are, individual user profiles, and what a "
            "given user has done recently. Member list and profile lookups "
            "are open to any teammate; per-user audit activity is gated "
            "to owners and admins."
        ),
        "capabilities": [
            "List active workspace members with role and persona",
            "Search workspace members by name or email substring",
            "Look up a single member's profile by user_id or email",
            "Surface a user's recent audit-log entries (owner/admin only)",
        ],
        "sample_prompts": [
            "Who is currently logged in?",
            "List the members of this workspace",
            "Find members whose email contains 'sarah'",
            "Show me Alice's profile",
            "What has Bob done in this workspace recently?",
        ],
    }

    # Tool names are byte-stable references — DB-stored
    # ``custom_profile.tool_whitelist`` entries reference them by string.
    # Renaming requires a data migration. See ADR 0003 + the agents skill.

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
        name="list_workspace_members",
        description=(
            "List active members of the current workspace. Use this for "
            "ANY 'who is in this workspace', 'list our team', 'who are the "
            "members', 'how many people are in this workspace' style "
            "question. Optional input as JSON: {\"role\"?: "
            "\"owner|admin|member|viewer\", \"status\"?: \"active|invited\", "
            "\"limit\"?: int}. Output: 'Workspace members (N active): "
            "• Name <email>  Role: ...  Persona: ...'."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INVALID_INPUT,
    )
    def list_workspace_members(self, input_str: str) -> str:
        return user_tools.list_workspace_members(self, input_str)

    @tool(
        name="search_workspace_members",
        description=(
            "Search workspace members by substring on name, username, or "
            "email. Scoped to this workspace only — does NOT search the "
            "platform-wide user table. Use this for ANY 'find the member "
            "named X', 'is there anyone called Y in this workspace', "
            "'search for sarah@example.com' style question. Input as JSON: "
            "{\"query\": str, \"limit\"?: int}. Output: same shape as "
            "list_workspace_members."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INVALID_INPUT,
    )
    def search_workspace_members(self, input_str: str) -> str:
        return user_tools.search_workspace_members(self, input_str)

    @tool(
        name="get_user_profile",
        description=(
            "Look up a single workspace member's profile by user_id "
            "(UUID) or email. Returns name, email, role, persona, status, "
            "and join date. Use this for ANY 'show me X's profile', "
            "'what's Y's role', 'when did Z join' style question. Input "
            "as JSON: {\"user_id\"?: uuid, \"email\"?: str, \"query\"?: "
            "str (UUID or email)}. At least one identifier required."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INVALID_INPUT,
    )
    def get_user_profile(self, input_str: str) -> str:
        return user_tools.get_user_profile(self, input_str)

    @tool(
        name="list_user_activity",
        description=(
            "Surface a user's recent audit-log entries within this "
            "workspace — every tracked field change actor'd by that user, "
            "newest first. Use this for ANY 'what has X done recently', "
            "'show me Y's audit history', 'what did Z change' style "
            "question. Input as JSON: {\"user_id\"?: uuid, \"email\"?: "
            "str, \"since\"?: ISO date (default 30 days ago), \"limit\"?: "
            "int (default 25, max 100)}. Owner/admin only."
        ),
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INVALID_INPUT,
    )
    @requires_role("owner", "admin")
    def list_user_activity(self, input_str: str) -> str:
        return user_tools.list_user_activity(self, input_str)
