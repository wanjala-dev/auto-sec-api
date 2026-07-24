"""Use case: provision the starter system workflows for a new workspace.

When a teamspace is created we want a small library of high-value system
workflows provisioned out of the box — no builder visit required — so the
team starts with a working automation set.

Each starter carries an **activation policy** (``activate``):

- ``activate=True``  → the workflow is published AND its trigger binding is
  left ACTIVE, so it fires immediately. Reserved for safe, internal, owner-
  facing automations (e.g. ``receipt-accountability`` — an internal nudge to
  the expense owner; no donor-facing email).
- ``activate=False`` → the workflow is still cloned + published (so it is a
  valid, gallery-visible automation an admin can inspect and turn on), but its
  auto-created trigger binding is parked INACTIVE so it does NOT fire until an
  admin explicitly activates it. Used for donor/contact-facing starters (e.g. a
  donation thank-you, a new-contact welcome) so a brand-new teamspace gets a
  richer library WITHOUT silently auto-emailing donors/contacts on day one.

This use case clones each designated system template into a per-workspace
``Workflow``, publishes it (which validates the graph, snapshots a version,
and wires up the start node's trigger ``WorkflowBinding`` workspace-wide), and
for ``activate=False`` starters then flips that binding inactive. It returns
the ids of the workflows it created.

Reuse, not reinvention: it goes through the SAME path the controller uses —
``WorkflowService.create_workflow`` (copies the template's ``default_graph``)
then ``WorkflowService.publish_workflow`` (full ``validate_graph`` +
``WorkflowVersion`` snapshot + ``_sync_start_node_bindings`` which creates the
active, workspace-wide ``source_id IS NULL`` binding derived from the start
node's ``config.triggerType``). The inactive park goes through
``WorkflowService.set_auto_bindings_active`` — no hand-rolled binding ORM.

Idempotent: a template that already has a (non-deleted) workflow in the
workspace is skipped, so re-running bootstrap never duplicates AND never
re-activates a binding an admin manually toggled (a re-seed never re-publishes
an existing starter, so it never re-syncs the binding). Best-effort: each
template is provisioned under its own guard so one bad template can't abort the
rest, and the method never raises — bootstrap must NEVER fail because workflow
seeding failed.

No Django/ORM imports — this is application layer; persistence is reached only
through ``WorkflowService``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The starter system templates provisioned into every new teamspace, each with
# its activation policy. Add a starter by appending an entry (the template must
# be seeded by ``seed_workflow_templates``). Order is provisioning order.
#
# Only ``activate=True`` starters fire on day one. The critical-finding alert is
# a safe, high-value internal automation (notify + AI-triage a critical finding)
# so it ships ON; the broader finding→SOAR forward ships OFF because it needs a
# webhook URL the admin supplies before it does anything.
#   - critical-finding-alert (finding_critical): notify + AI triage → ON.
#   - finding-soar-webhook (finding_raised): forward to SOAR → OFF (needs a URL).
STARTER_TEMPLATES: list[dict[str, Any]] = [
    {"template_id": "critical-finding-alert", "activate": True},
    {"template_id": "finding-soar-webhook", "activate": False},
]

# Goal stored on the cloned workflow. "general" is the unconstrained goal
# (imposes no trigger restriction), so the workflow stays valid for any
# starter template's trigger and for any later edit-and-republish.
_STARTER_WORKFLOW_GOAL = "general"


class SeedWorkspaceStarterWorkflowsUseCase:
    """Provision the starter system workflows for a workspace (idempotent)."""

    def __init__(self, service: Any | None = None) -> None:
        if service is None:
            from components.workflow.application.service import WorkflowService

            service = WorkflowService()
        self._service = service

    def execute(self, workspace_id: Any) -> list[Any]:
        """Provision each starter template into *workspace_id*.

        Returns the ids of the workflows created on this run (skipped /
        already-present templates are not included). Never raises.
        """
        created: list[Any] = []
        for starter in STARTER_TEMPLATES:
            template_id = starter["template_id"]
            activate = bool(starter.get("activate", False))
            try:
                workflow = self._provision_one(workspace_id, template_id, activate)
                if workflow is not None:
                    created.append(workflow.id)
            except Exception:
                # Best-effort per template: a single failure must not block the
                # others, and must never propagate into the bootstrap caller.
                logger.exception(
                    "starter_workflow_seed_failed workspace_id=%s template_id=%s",
                    workspace_id,
                    template_id,
                )
        return created

    def _provision_one(self, workspace_id: Any, template_id: str, activate: bool) -> Any | None:
        template = self._service.get_template_by_id(template_id)
        if template is None:
            # Fresh DB / templates not seeded yet — bootstrap can re-run later.
            logger.warning(
                "starter_workflow_template_missing workspace_id=%s template_id=%s",
                workspace_id,
                template_id,
            )
            return None

        # Idempotency: skip when this workspace already has a (live) workflow
        # cloned from this template — re-running bootstrap must NOT duplicate,
        # and (because we never re-publish) must NOT re-activate a binding an
        # admin manually toggled.
        already = self._service.get_workflows(
            workspace_id=str(workspace_id),
            template_id=template_id,
            exclude_deleted=True,
        )
        if already.exists():
            logger.info(
                "starter_workflow_already_present workspace_id=%s template_id=%s",
                workspace_id,
                template_id,
            )
            return None

        workflow = self._service.create_workflow(
            workspace_id=str(workspace_id),
            name=template.label,
            description=template.description,
            goal=_STARTER_WORKFLOW_GOAL,
            template_id=template_id,
            is_custom=False,
            status="draft",
            graph=template.default_graph,
        )
        # Publish validates the graph, snapshots a WorkflowVersion, flips the
        # workflow live, and syncs the start-node trigger binding (active,
        # workspace-wide) so it actually fires.
        self._service.publish_workflow(workflow, notes="Auto-seeded starter workflow")

        if not activate:
            # Park the auto-created binding INACTIVE: the workflow is published
            # and gallery-visible, but it must NOT fire until an admin turns it
            # on. publish always creates an ACTIVE binding, so flip it here.
            self._service.set_auto_bindings_active(workflow.id, False)
            self._assert_bindings_inactive(workspace_id, workflow, template_id)

        logger.info(
            "starter_workflow_provisioned workspace_id=%s template_id=%s workflow_id=%s activate=%s",
            workspace_id,
            template_id,
            workflow.id,
            activate,
        )
        return workflow

    def _assert_bindings_inactive(self, workspace_id: Any, workflow: Any, template_id: str) -> None:
        """Verify an ``activate=False`` starter's bindings ended up inactive.

        A defensive check (logged, not raised — best-effort) that the park
        actually took, so a regression in the binding plumbing surfaces in logs
        rather than silently shipping a live donor-facing automation.
        """
        bindings = self._service.get_bindings(workflow_id=str(workflow.id))
        active = [b for b in bindings if getattr(b, "is_active", False)]
        if active:
            logger.warning(
                "starter_workflow_binding_still_active workspace_id=%s template_id=%s workflow_id=%s active_count=%s",
                workspace_id,
                template_id,
                workflow.id,
                len(active),
            )
