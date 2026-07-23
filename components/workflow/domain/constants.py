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


SOURCE_TYPES = (
    "directory",
    "task",
    "event",
    "campaign",
    "sponsorship",
    "project",
    "grant",
    "document",
    # ``form`` — a published donation form. The ``form_completed`` trigger fires
    # when a donor checks out a form (components/donation_forms). The form is a
    # distinct domain from the membership ``directory``: a form checkout produces
    # an anonymous donor (identified by email at submit time), not a
    # WorkspaceMembership row, so ``directory`` would mislabel it.
    "form",
    # ``communication`` — a workspace newsletter / email broadcast. The
    # ``email_sent`` trigger fires once per recipient when a newsletter is sent
    # (components/content). The send is a communications/content concern, not a
    # ``campaign`` (a separate bounded context), so it gets its own source_type.
    "communication",
    # ``budget`` — a budget ledger entry. The ``transaction_recorded`` trigger
    # fires when an EXPENSE Transaction is first committed (components/budgeting).
    # The subject of a budget automation is the transaction itself, not a
    # directory contact, so it gets its own source_type (the run targets the
    # transaction id; the reminder email resolves the owner from the payload).
    "budget",
    # ``receipt`` — a receipt attached to a budget transaction. The
    # ``receipt_attached`` trigger fires when a TransactionReceipt is linked to
    # an expense (components/budgeting sync_receipt). It is the resolving event
    # for the receipt-accountability ``wait_until`` — it correlates by the
    # transaction id, so the waiting run wakes Yes when the receipt arrives.
    "receipt",
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
    TriggerDefinition(
        id="contact_added",
        source_type="directory",
        label="New contact added",
        goal_ids=("campaign", "sponsorship", "event"),
    ),
    # Emitted by the member-role update endpoint (WorkspaceMemberRoleView) when a
    # directory contact's role changes — a genuine, contact-targeted directory
    # mutation. See components/membership/api/groups_controller.py.
    TriggerDefinition(
        id="contact_updated",
        source_type="directory",
        label="Contact updated",
        goal_ids=("campaign", "sponsorship"),
    ),
    # NOTE: ``contact_tagged`` was REMOVED from the catalog (it was catalogued but
    # never emitted). The only writer of WorkspaceMembership.tags is the workflow
    # ``add_tag`` action executor (node_actions.py) — there is NO manual/API
    # tagging surface for directory contacts. Emitting ``contact_tagged`` from the
    # only available point (the add_tag executor) would create an infinite loop:
    # contact_tagged trigger -> add_tag action -> contact_tagged -> ... With no
    # manual-vs-automated tag source to distinguish, the honest choice per the
    # trigger-completeness rule is to remove it rather than ship a loop. Re-add it
    # the day a manual contact-tagging endpoint exists, emitting only from there.
    TriggerDefinition(
        id="task_created",
        source_type="task",
        label="Task created",
        goal_ids=("campaign", "event"),
    ),
    TriggerDefinition(
        id="task_completed",
        source_type="task",
        label="Task completed",
        goal_ids=("campaign", "event", "sponsorship"),
    ),
    # Emitted by project/api/controller.py on task assignment. Was previously
    # absent from the catalog, so WorkflowBindingSerializer.validate rejected any
    # binding to it — the event fired into the void. Cataloguing it makes the
    # trigger bindable.
    TriggerDefinition(
        id="task_assigned",
        source_type="task",
        label="Task assigned",
        goal_ids=("campaign", "event", "sponsorship", "agents"),
    ),
    # Phase 4 of the Agents-as-Teammates migration. Fires whenever a
    # Task's ``column`` FK changes (drag-drop on the Kanban or PATCH
    # to update-task). The event payload carries previous_column_id,
    # new_column_id, source_type — the workflow's decision node
    # filters on source_type prefix + new column title (e.g.
    # ``source_type LIKE 'ai.%' AND new_column_title = 'Accepted'``).
    TriggerDefinition(
        id="task_moved_column",
        source_type="task",
        label="Task moved between columns",
        goal_ids=("campaign", "event", "sponsorship", "agents"),
        compatible_node_types=("start",),
    ),
    TriggerDefinition(
        id="event_rsvp_yes",
        source_type="event",
        label="Event RSVP yes",
        goal_ids=("event", "campaign"),
    ),
    TriggerDefinition(
        id="event_checkin",
        source_type="event",
        label="Event check-in",
        goal_ids=("event",),
    ),
    TriggerDefinition(
        id="campaign_opened",
        source_type="campaign",
        label="Campaign message opened",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="campaign_clicked",
        source_type="campaign",
        label="Campaign link clicked",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="donation_received",
        source_type="sponsorship",
        label="Donation received",
        goal_ids=("sponsorship",),
    ),
    TriggerDefinition(
        id="sponsorship_started",
        source_type="sponsorship",
        label="Sponsorship started",
        goal_ids=("sponsorship",),
    ),
    TriggerDefinition(
        id="project_milestone_done",
        source_type="project",
        label="Project milestone completed",
        goal_ids=("campaign", "event"),
    ),
    TriggerDefinition(
        id="project_update_posted",
        source_type="project",
        label="Project update posted",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="grant_submitted",
        source_type="grant",
        label="Grant submitted",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="grant_awarded",
        source_type="grant",
        label="Grant awarded",
        goal_ids=("sponsorship",),
    ),
    # ── Document triggers ────────────────────────────────────
    TriggerDefinition(
        id="document_uploaded",
        source_type="document",
        label="Document uploaded",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="document_processed",
        source_type="document",
        label="Document processed",
        goal_ids=("campaign", "sponsorship"),
    ),
    TriggerDefinition(
        id="document_applied",
        source_type="document",
        label="Document import applied",
        goal_ids=("campaign", "sponsorship"),
    ),
    # ── Donation-form trigger ────────────────────────────────
    # Emitted when a donor checks out a published donation form
    # (components/donation_forms). The donor is anonymous at submit time, so the
    # run targets the donor by email (their stable contact identity), mirroring
    # the donation_received/sponsorship_started fallback.
    TriggerDefinition(
        id="form_completed",
        source_type="form",
        label="Donation form completed",
        goal_ids=("campaign", "sponsorship", "event"),
    ),
    # ── Communication trigger ────────────────────────────────
    # Emitted once per recipient when a workspace newsletter is sent
    # (components/content SendNewsletterUseCase). Recipients are newsletter
    # subscribers (not WorkspaceMembership directory rows), so each run targets
    # the subscriber by email.
    TriggerDefinition(
        id="email_sent",
        source_type="communication",
        label="Contact receives an email",
        goal_ids=("campaign", "sponsorship"),
    ),
    # ── Budget / receipt-accountability triggers ─────────────
    # Emitted when an EXPENSE Transaction is first committed
    # (components/budgeting django_budget_signal_bridge, created transition).
    # The run targets the TRANSACTION id (not a contact) — the subject of a
    # receipt-accountability automation is the expense; the reminder email
    # resolves the owner from the trigger payload's ``owner_email``.
    TriggerDefinition(
        id="transaction_recorded",
        source_type="budget",
        label="Expense recorded",
        goal_ids=("campaign",),
    ),
    # Emitted when a receipt file is attached to a transaction
    # (components/budgeting sync_receipt). It correlates by transaction id, so a
    # ``wait_until(event="receipt_attached")`` armed by ``transaction_recorded``
    # wakes Yes when the matching receipt arrives.
    TriggerDefinition(
        id="receipt_attached",
        source_type="receipt",
        label="Receipt attached",
        goal_ids=("campaign",),
    ),
    # ── Security finding / alert triggers ────────────────────
    # Emitted by components/agents specialist_persistence_service when a
    # detector/specialist files a finding on the SOC board. ``finding_raised``
    # fires for every finding; the severity-scoped triggers fire additionally
    # when the band matches, so a playbook can bind straight to "critical
    # finding" without a condition node. The run targets the finding (task id);
    # the payload carries severity / service / detector / impact_score.
    TriggerDefinition(
        id="finding_raised",
        source_type="finding",
        label="Security finding raised",
        goal_ids=("security",),
    ),
    TriggerDefinition(
        id="finding_critical",
        source_type="finding",
        label="Critical finding raised",
        goal_ids=("security",),
    ),
    TriggerDefinition(
        id="finding_high",
        source_type="finding",
        label="High-severity finding raised",
        goal_ids=("security",),
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
