"""Default agent type catalogue for bootstrap registrations."""

from __future__ import annotations

DEFAULT_AGENT_TYPES: list[dict[str, object]] = [
    {
        "slug": "ai_teammate",
        "name": "Orchestrator Agent",
        "description": "The brain: routes tasks between agents, keeps org context, and tracks progress.",
        "class_path": "components.agents.infrastructure.adapters.langchain.agents.ai_teammate_agent.AiTeammateAgent",
        "aliases": ["ai_teammate_agent", "orchestrator", "orchestrator_agent", "planner"],
        "default_config": {
            "profile": {
                "name": "Orchestrator Agent",
                "summary": "Routes work across specialised agents, maintains org goals/constraints, and keeps execution auditable.",
                "capabilities": [
                    "Run registered detectors to surface work needing attention",
                    "Delegate to domain agents with entitlement checks",
                    "Log AI Actions for audit and approval/revert flows",
                ],
                "sample_prompts": [
                    "Summarise what the Orchestrator delegated today.",
                    "List any actions waiting for approval.",
                ],
            }
        },
    },
    {
        "slug": "task_agent",
        "name": "Task Agent",
        "description": "Coordinates tasks, assignments, and progress tracking for teams.",
        "class_path": "components.agents.infrastructure.adapters.langchain.agents.task_agent.TaskAgent",
        "aliases": ["task", "task_management"],
        "default_config": {
            "profile": {
                "name": "Task Agent",
                "summary": "Keeps team work moving by creating tasks, assigning owners, and tracking status updates.",
                "capabilities": [
                    "Create and prioritise tasks for projects",
                    "Assign work to team members and adjust due dates",
                    "Summarise task progress and surface blockers",
                ],
                "sample_prompts": [
                    "Create a task to draft the annual report due next Friday.",
                    "Who is assigned to the website redesign task?",
                    "Give me a status overview of all in-progress tasks.",
                ],
            }
        },
    },
    {
        "slug": "project_agent",
        "name": "Project Agent",
        "description": "Supports project planning, tracking, and reporting.",
        "class_path": "components.agents.infrastructure.adapters.langchain.agents.project_agent.ProjectAgent",
        "aliases": ["project", "project_management"],
        "default_config": {
            "profile": {
                "name": "Project Agent",
                "summary": "Plans projects end-to-end and keeps stakeholders aligned.",
                "capabilities": [
                    "Create and configure new projects with teams",
                    "Report on project status and timeline health",
                    "Highlight upcoming milestones and overdue tasks",
                ],
                "sample_prompts": [
                    "Create a project called Community Clinic Launch starting next month.",
                    "List any overdue milestones for our active projects.",
                    "What's the status of Project Sunrise?",
                ],
            }
        },
    },
    {
        "slug": "user_agent",
        "name": "User Agent",
        "description": "Workspace member identity, profiles, and per-user audit activity.",
        "class_path": "components.agents.infrastructure.adapters.langchain.agents.user_agent.UserAgent",
        "aliases": ["user", "users", "identity_agent", "identity", "members"],
        "default_config": {
            "profile": {
                "name": "User Agent",
                "summary": "Answers questions about people in this workspace — who the active members are, individual user profiles, and what a given user has done recently. Per-user audit activity is gated to owners and admins.",
                "capabilities": [
                    "List active workspace members with names, roles, and personas",
                    "Search workspace members by name or email substring",
                    "Look up a single member's profile by user_id or email",
                    "Surface a specific member's recent audit-log activity (owner/admin only)",
                ],
                "sample_prompts": [
                    "Who is on the team?",
                    "Search for the member named sarah.",
                    "Show me Bob's profile.",
                    "What has Carol done in the last week?",
                ],
            }
        },
    },
]

# NOTE (single source of truth): this list is now OPTIONAL. It holds only the
# richer per-slug config overrides for the four foundational agents. Every other
# ``@register_agent`` agent (triage_agent, workspace_agent, log_watch_agent, and
# any new one) auto-syncs to an ``AgentType`` row from its class ``profile`` via
# ``sync_agent_types_from_registry`` — no edit here required. Add an entry only
# when an agent needs config beyond what its ``profile`` expresses.
