"""Workflow constants shared across serializers, views, and tasks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerDefinition:
    """Describe a workflow trigger for validation and API exposure."""

    id: str
    source_type: str
    label: str
    goal_ids: tuple[str, ...] = ()
    compatible_node_types: tuple[str, ...] = ("start",)


# Security-product source types. The nonprofit source types (directory, event,
# campaign, sponsorship, grant, form, communication, budget, receipt) were
# removed with the fork — their contexts no longer exist, so their triggers
# never fired. A SOC workflow acts on board work (task/project), library
# documents, and — the headline — security findings.
SOURCE_TYPES = (
    "task",
    "project",
    "document",
    # ``finding`` — a security finding on the SOC board. A finding is an
    # ``ai.*`` Kanban Task filed by a detector/specialist. The ``finding_*``
    # triggers fire when one lands (see specialist_persistence_service), so a
    # workflow can run a playbook on an alert: notify, open a ticket, run the AI
    # triage agent, webhook to a SOAR. The run targets the finding (task id);
    # the payload carries severity / service / detector so condition + action
    # nodes can branch and act on it.
    "finding",
)

TARGET_TYPES = ("contact", "group")

NODE_TYPES = (
    "start",
    "end",
    "message",
    "data_request",
    # ``decision`` is the LEGACY manual branch — it pauses the run and waits for
    # an external complete_step API call. Prefer ``condition`` (autonomous,
    # predicate-evaluated) for new automations; keep ``decision`` for genuine
    # human-in-the-loop approval steps.
    "decision",
    # ``condition`` — autonomous branch. Evaluates a predicate against the run
    # context server-side and takes the Yes/No edge with no human in the loop.
    "condition",
    # ``wait_until`` — autonomous time-boxed wait. Waits for a domain event
    # (e.g. the contact makes a transaction) up to a timeout, then branches
    # Yes (event happened) / No (timed out). This is Keela's "wait until ...".
    "wait_until",
    # ``switch`` — autonomous MULTI-WAY branch. Evaluates an ordered list of
    # cases (each a predicate, same DSL as ``condition``) against the run context
    # and takes the first matching case's labelled edge; falls through to a
    # ``default`` edge when none match. ``condition`` is the 2-way (yes/no) form;
    # ``switch`` generalises it to N outcomes with no human in the loop.
    "switch",
    "task",
    "ai",
    "assign",
    # ``add_tag`` / ``remove_tag`` — Keela-style contact tagging. Add or remove a
    # workspace-scoped Tag on the directory contact's WorkspaceMembership.
    "add_tag",
    "remove_tag",
    # ``update_field`` — write an allow-listed CRM field on the contact's profile.
    "update_field",
    "wait",
    "webhook",
    # Phase 4 of the Agents-as-Teammates migration — publishes a
    # shared-kernel domain event so downstream specialist handlers
    # can react to workflow-driven outcomes (e.g. user accepts an
    # AI finding on the Kanban → fire a TaskAcceptedFromBoard event).
    "publish_event",
)

TRIGGER_CATALOG = [
    # ── Board work (tasks / projects) ────────────────────────
    # All emitted by the project context (create/update task repositories +
    # controller). Findings ARE ai.* tasks, so task_* also fire for them; the
    # dedicated finding_* triggers below carry the security payload.
    TriggerDefinition(id="task_created", source_type="task", label="Task created", goal_ids=("security",)),
    TriggerDefinition(id="task_completed", source_type="task", label="Task completed", goal_ids=("security",)),
    TriggerDefinition(id="task_assigned", source_type="task", label="Task assigned", goal_ids=("security",)),
    TriggerDefinition(
        id="task_moved_column",
        source_type="task",
        label="Task moved between columns",
        goal_ids=("security",),
    ),
    TriggerDefinition(
        id="project_milestone_done",
        source_type="project",
        label="Project milestone completed",
        goal_ids=("security",),
    ),
    TriggerDefinition(
        id="project_update_posted",
        source_type="project",
        label="Project update posted",
        goal_ids=("security",),
    ),
    # ── Documents (library / uploads) ────────────────────────
    TriggerDefinition(id="document_uploaded", source_type="document", label="Document uploaded", goal_ids=("security",)),
    TriggerDefinition(
        id="document_processed", source_type="document", label="Document processed", goal_ids=("security",)
    ),
    TriggerDefinition(
        id="document_applied", source_type="document", label="Document import applied", goal_ids=("security",)
    ),
    # ── Security finding / alert triggers ────────────────────
    # Emitted by components/agents specialist_persistence_service when a
    # detector/specialist files a finding on the SOC board. finding_raised fires
    # for every finding; the severity-scoped triggers fire additionally when the
    # band matches, so a playbook can bind straight to "critical finding". The
    # run targets the finding (task id); payload carries severity/service/detector.
    TriggerDefinition(id="finding_raised", source_type="finding", label="Security finding raised", goal_ids=("security",)),
    TriggerDefinition(
        id="finding_critical", source_type="finding", label="Critical finding raised", goal_ids=("security",)
    ),
    TriggerDefinition(
        id="finding_high", source_type="finding", label="High-severity finding raised", goal_ids=("security",)
    ),
]


WORKFLOW_STATUSES = (
    "draft",
    "published",
    "paused",
    "archived",
)

RUN_STATUSES = (
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "canceled",
)

STEP_EVENT_TYPES = (
    "entered",
    "completed",
    "failed",
    "branched",
)

STEP_STATES = (
    "pending",
    "running",
    "waiting",
    "waiting_input",
    "completed",
    "failed",
)

EVENT_STATUSES = (
    "pending",
    "processing",
    "processed",
    "failed",
)
