"""Seed system workflow templates.

Usage:
    python manage.py seed_workflow_templates          # upsert all
    python manage.py seed_workflow_templates --dry-run # preview without writing

Every template in ``SYSTEM_TEMPLATES`` is authored to be **publish-ready and
autonomous**: its ``default_graph`` passes ``validate_graph`` (the publish gate)
with zero errors AND runs end-to-end with no human-in-the-loop step *unless* a
human decision is genuinely required (grant approve/decline, document review).

The autonomous-engine rules (see the ``workflow`` skill + ``.claude/rules``):

- Every ``message`` node carries ``channel`` + a real ``body`` so it publishes
  and actually sends. (An empty-body message fails ``message_missing_payload``.)
- Branch points are ``wait_until`` (wait for a domain event up to a timeout, then
  branch Yes=event-arrived / No=timed-out) or ``condition`` (evaluate a predicate
  against the run context and branch with no human). Both need ≥2 *labelled*
  outgoing edges — we label them ``yes``/``no`` so ``WorkflowGraph.branch_target``
  resolves deterministically (not just positionally).
- The legacy manual ``decision`` node is used ONLY where a person must judge
  (grant approve/decline, import review approve/reject) — those steps are meant
  to pause for an operator's ``complete_step`` call.
- ``task`` / ``assign`` nodes no-op gracefully in a *system* template (they need a
  workspace-specific ``column_id``/``user_id`` the author supplies after cloning);
  they never fail publish.

``WorkflowTemplate.default_graph`` is validated by ``WorkflowTemplateSerializer``
on create/update with the same ``validate_graph`` — and
``components/workflow/tests/unit/test_seeded_templates_publish.py`` asserts every
template here passes. Edit a graph below and that test is the regression lock.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

# Workspace-default tip: bodies are sent as-is (no placeholder resolution on the
# raw ``body`` path), so keep copy generic — a literal ``{{first_name}}`` would
# render unresolved. To personalise, set ``template_id`` to a content
# WritingTemplate instead (rendered by ``_render_template_body``).

SYSTEM_TEMPLATES = [
    # ── Critical Finding — Alert & Triage ─────────────────────
    {
        "id": "critical-finding-alert",
        "label": "Critical Finding — Alert & Triage",
        "category": "security",
        "version": "1",
        "description": "When a critical finding lands, alert the SOC in-app and run the AI triage agent on it automatically.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Critical finding raised", "subtitle": "A critical alert lands on the board", "config": {"triggerType": "finding_critical"}},
                {"id": "notify", "type": "message", "label": "Alert the SOC", "subtitle": "In-app notification to the team", "config": {"channel": "in_app", "body": "A critical security finding was just raised. Triage is starting automatically."}},
                {"id": "triage", "type": "ai", "label": "AI triage", "subtitle": "Run the triage agent on the finding", "config": {"prompt": "Triage this critical security finding: assess blast radius, likely root cause, and the first containment step. Ground every claim in the finding evidence."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Triage complete", "config": {}},
            ],
            "edges": [
                {"id": "cfa-0", "from": "start", "to": "notify"},
                {"id": "cfa-1", "from": "notify", "to": "triage"},
                {"id": "cfa-2", "from": "triage", "to": "end"},
            ],
        },
    },
    # ── High Finding — Auto-Triage ────────────────────────────
    {
        "id": "high-finding-triage",
        "label": "High Finding — Auto-Triage",
        "category": "security",
        "version": "1",
        "description": "Run the AI triage agent on every high-severity finding, then notify the team with the result.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "High finding raised", "subtitle": "A high-severity alert lands", "config": {"triggerType": "finding_high"}},
                {"id": "triage", "type": "ai", "label": "AI triage", "subtitle": "Assess and recommend", "config": {"prompt": "Triage this high-severity finding and recommend whether it needs immediate action or can be queued. Ground the recommendation in the finding evidence."}},
                {"id": "notify", "type": "message", "label": "Notify the team", "subtitle": "Share the triage result", "config": {"channel": "in_app", "body": "A high-severity finding was triaged automatically — review the recommendation on the board."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Complete", "config": {}},
            ],
            "edges": [
                {"id": "hft-0", "from": "start", "to": "triage"},
                {"id": "hft-1", "from": "triage", "to": "notify"},
                {"id": "hft-2", "from": "notify", "to": "end"},
            ],
        },
    },
    # ── Finding → SOAR Webhook (severity-branched) ────────────
    {
        "id": "finding-soar-webhook",
        "label": "Finding → SOAR Webhook",
        "category": "security",
        "version": "1",
        "description": "On every finding, branch on severity: forward high/critical findings to an external SOAR webhook; log the rest.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Finding raised", "subtitle": "Any finding lands on the board", "config": {"triggerType": "finding_raised"}},
                {"id": "severe", "type": "condition", "label": "High or critical?", "subtitle": "Branch on severity band", "config": {"predicate": {"match": "any", "conditions": [{"field": "severity", "op": "eq", "value": "high"}, {"field": "severity", "op": "eq", "value": "critical"}]}}},
                {"id": "forward", "type": "webhook", "label": "Forward to SOAR", "subtitle": "POST the finding to your SOAR", "config": {"url": "", "method": "POST"}},
                {"id": "log", "type": "message", "label": "Log low/medium", "subtitle": "Record for the record", "config": {"channel": "in_app", "body": "A lower-severity finding was logged and not escalated."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Complete", "config": {}},
            ],
            "edges": [
                {"id": "fsw-0", "from": "start", "to": "severe"},
                {"id": "fsw-1", "from": "severe", "to": "forward", "label": "yes"},
                {"id": "fsw-2", "from": "severe", "to": "log", "label": "no"},
                {"id": "fsw-3", "from": "forward", "to": "end"},
                {"id": "fsw-4", "from": "log", "to": "end"},
            ],
        },
    },
    # ── Phase 4 of the Agents-as-Teammates migration ──────────────────
    # Fires whenever a task with ``source_type LIKE 'ai.%'`` moves into the
    # ``Accepted`` column on the AI agent team board — publishes a
    # ``TaskAcceptedFromBoard`` shared-kernel event for downstream specialists.
    {
        "id": "ai-findings-accepted",
        "label": "AI Findings Accepted",
        "category": "agents",
        "version": "1",
        "description": (
            "When an AI-finding task moves into the Accepted column on "
            "the agent team board, publish a TaskAcceptedFromBoard "
            "event so downstream specialist agents can react."
        ),
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Task moves between columns", "subtitle": "Triggered by Kanban drag-drop or PATCH", "config": {"triggerType": "task_moved_column"}},
                {"id": "publish", "type": "publish_event", "label": "Publish TaskAcceptedFromBoard", "subtitle": "Fan out to specialist handlers", "config": {"event_type": "task_accepted_from_board", "filters": {"task_source_type_prefix": "ai.", "new_column_title": "Accepted"}}},
                {"id": "end", "type": "end", "label": "Done", "subtitle": "Workflow complete", "config": {}},
            ],
            "edges": [
                {"id": "ai-findings-0", "from": "start", "to": "publish"},
                {"id": "ai-findings-1", "from": "publish", "to": "end"},
            ],
        },
    },
]

# The nonprofit template gallery (sponsor/donation/grant/campaign/event/receipt)
# was retired with the fork — those source types + triggers no longer exist, so
# the seeder DELETES the stale rows. ``product-launch`` was an even earlier
# off-ICP SaaS demo.
DEPRECATED_TEMPLATE_IDS = [
    "product-launch",
    "sponsor",
    "event",
    "nurture",
    "automation",
    "grants",
    "donation-thanks",
    "event-followup",
    "sponsor-onboard",
    "grant-deadline",
    "campaign-reengage",
    "document-import",
    "receipt-accountability",
]


class Command(BaseCommand):
    help = "Seed system workflow templates (idempotent upsert + retire deprecated)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        from infrastructure.persistence.workspaces.workflows.models import WorkflowTemplate

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for tmpl in SYSTEM_TEMPLATES:
            template_id = tmpl["id"]
            defaults = {
                "label": tmpl["label"],
                "description": tmpl["description"],
                "category": tmpl["category"],
                "version": tmpl["version"],
                "is_system": True,
                "default_graph": tmpl["default_graph"],
                "workspace": None,
                "created_by": None,
            }

            try:
                existing = WorkflowTemplate.objects.get(id=template_id)
                # Only update if version changed
                if existing.version != tmpl["version"]:
                    if not dry_run:
                        for field, value in defaults.items():
                            setattr(existing, field, value)
                        existing.save()
                    updated_count += 1
                    self.stdout.write(f"  Updated: {template_id} (v{existing.version} -> v{tmpl['version']})")
                else:
                    unchanged_count += 1
                    self.stdout.write(f"  Unchanged: {template_id} (v{tmpl['version']})")
            except WorkflowTemplate.DoesNotExist:
                if not dry_run:
                    WorkflowTemplate.objects.create(id=template_id, **defaults)
                created_count += 1
                self.stdout.write(f"  Created: {template_id} (v{tmpl['version']})")

        deleted_count = 0
        for dead_id in DEPRECATED_TEMPLATE_IDS:
            qs = WorkflowTemplate.objects.filter(id=dead_id, is_system=True)
            if qs.exists():
                if not dry_run:
                    qs.delete()
                deleted_count += 1
                self.stdout.write(f"  Retired: {dead_id}")

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix}Done. Created: {created_count}, Updated: {updated_count}, "
                f"Unchanged: {unchanged_count}, Retired: {deleted_count}"
            )
        )
