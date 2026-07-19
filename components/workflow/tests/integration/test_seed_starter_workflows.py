"""Integration tests for auto-seeding starter workflows on teamspace creation.

Covers the ``SeedWorkspaceStarterWorkflowsUseCase`` (clone template -> publish
-> binding), the per-starter ACTIVATION POLICY (``activate=True`` => active
binding that fires immediately; ``activate=False`` => published workflow whose
binding is parked INACTIVE so it does not fire until an admin turns it on), its
idempotency (no dup, never re-activates an admin-toggled binding), its
best-effort behaviour when a template is missing, the trigger-completeness of
every added starter (catalogued AND emitted with a contact target), and the
bootstrap wiring.
"""
from __future__ import annotations

import pathlib

import pytest

from components.workflow.application.use_cases.seed_workspace_starter_workflows_use_case import (
    STARTER_TEMPLATES,
    SeedWorkspaceStarterWorkflowsUseCase,
)
from components.workflow.cli.management.commands.seed_workflow_templates import (
    SYSTEM_TEMPLATES,
)
from components.workflow.domain.constants import TRIGGER_CATALOG
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowBinding,
    WorkflowTemplate,
)

pytestmark = pytest.mark.django_db

RECEIPT_TEMPLATE_ID = "receipt-accountability"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]


def _seed_template(template_id: str) -> WorkflowTemplate:
    """Create a system template (fidelity to the seed command)."""
    tmpl = next(t for t in SYSTEM_TEMPLATES if t["id"] == template_id)
    return WorkflowTemplate.objects.create(
        id=tmpl["id"],
        label=tmpl["label"],
        description=tmpl["description"],
        category=tmpl["category"],
        version=tmpl["version"],
        is_system=True,
        default_graph=tmpl["default_graph"],
    )


def _seed_all_starters() -> None:
    for starter in STARTER_TEMPLATES:
        _seed_template(starter["template_id"])


def _start_trigger(template_id: str) -> str:
    """The start node's trigger id for a system template."""
    tmpl = next(t for t in SYSTEM_TEMPLATES if t["id"] == template_id)
    start = next(n for n in tmpl["default_graph"]["nodes"] if n["type"] == "start")
    return start["config"]["triggerType"]


class TestActivationPolicy:
    def test_active_starter_has_active_binding(self, workspace_factory):
        """``activate=True`` => published workflow + ACTIVE binding (fires now)."""
        _seed_all_starters()
        workspace = workspace_factory()

        SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        workflow = Workflow.objects.get(
            workspace=workspace, template_id=RECEIPT_TEMPLATE_ID, is_deleted=False
        )
        assert workflow.status == Workflow.Status.PUBLISHED

        binding = WorkflowBinding.objects.get(
            workflow=workflow, source_id__isnull=True
        )
        assert binding.is_active is True
        assert binding.source_type == "budget"
        assert binding.trigger_type == "transaction_recorded"

    @pytest.mark.parametrize(
        "template_id",
        [s["template_id"] for s in STARTER_TEMPLATES if not s["activate"]],
    )
    def test_inactive_starter_exists_but_binding_is_inactive(
        self, template_id, workspace_factory
    ):
        """``activate=False`` => workflow published, but binding parked INACTIVE."""
        _seed_all_starters()
        workspace = workspace_factory()

        SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        workflow = Workflow.objects.get(
            workspace=workspace, template_id=template_id, is_deleted=False
        )
        # Published so it is a valid, gallery-visible automation an admin can turn on.
        assert workflow.status == Workflow.Status.PUBLISHED

        bindings = WorkflowBinding.objects.filter(
            workflow=workflow, source_id__isnull=True
        )
        # A binding exists (publish wired the trigger) but it must NOT be active.
        assert bindings.exists()
        assert not bindings.filter(is_active=True).exists()

    def test_all_starters_created_on_first_run(self, workspace_factory):
        _seed_all_starters()
        workspace = workspace_factory()
        created = SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)
        assert len(created) == len(STARTER_TEMPLATES)


class TestIdempotency:
    def test_no_duplicate_on_rerun(self, workspace_factory):
        _seed_all_starters()
        workspace = workspace_factory()

        first = SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)
        second = SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        assert len(first) == len(STARTER_TEMPLATES)
        assert second == []  # nothing created the second time
        for starter in STARTER_TEMPLATES:
            assert (
                Workflow.objects.filter(
                    workspace=workspace,
                    template_id=starter["template_id"],
                    is_deleted=False,
                ).count()
                == 1
            )

    def test_rerun_does_not_reactivate_admin_toggled_binding(self, workspace_factory):
        """An admin who activated an inactive starter must keep it active on re-seed.

        And one who deactivated the receipt (active) starter must keep it off.
        """
        _seed_all_starters()
        workspace = workspace_factory()
        SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        # Admin turns ON a donor-facing starter (donation-thanks) ...
        thanks_wf = Workflow.objects.get(
            workspace=workspace, template_id="donation-thanks", is_deleted=False
        )
        WorkflowBinding.objects.filter(
            workflow=thanks_wf, source_id__isnull=True
        ).update(is_active=True)
        # ... and turns OFF the receipt starter that shipped active.
        receipt_wf = Workflow.objects.get(
            workspace=workspace, template_id=RECEIPT_TEMPLATE_ID, is_deleted=False
        )
        WorkflowBinding.objects.filter(
            workflow=receipt_wf, source_id__isnull=True
        ).update(is_active=False)

        # Re-seed must leave both as the admin set them (it never re-publishes).
        SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        assert WorkflowBinding.objects.get(
            workflow=thanks_wf, source_id__isnull=True
        ).is_active is True
        assert WorkflowBinding.objects.get(
            workflow=receipt_wf, source_id__isnull=True
        ).is_active is False


class TestBestEffort:
    def test_missing_template_is_best_effort_noop(self, workspace_factory):
        # No templates seeded -> no workflow, no binding, no raise.
        workspace = workspace_factory()
        created = SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)
        assert created == []
        assert not Workflow.objects.filter(workspace=workspace).exists()

    def test_one_missing_template_does_not_block_others(self, workspace_factory):
        # Seed only the receipt template; the others are absent.
        _seed_template(RECEIPT_TEMPLATE_ID)
        workspace = workspace_factory()
        created = SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)
        # The present one is still provisioned despite the missing siblings.
        assert len(created) == 1
        assert Workflow.objects.filter(
            workspace=workspace, template_id=RECEIPT_TEMPLATE_ID
        ).exists()


class TestTriggerCompleteness:
    """Every starter's trigger must be catalogued AND have a real emit site.

    The trigger-is-a-contract rule (workflow skill §3): a binding only fires if
    the trigger id is in TRIGGER_CATALOG *and* some context actually calls
    ``emit_workflow_event(trigger_type=...)``. A starter whose trigger isn't
    emitted would be a binding that can never fire — so it must not be a starter.
    """

    _CATALOG_IDS = {t.id for t in TRIGGER_CATALOG}

    @pytest.mark.parametrize(
        "template_id", [s["template_id"] for s in STARTER_TEMPLATES]
    )
    def test_starter_trigger_is_catalogued(self, template_id):
        assert _start_trigger(template_id) in self._CATALOG_IDS

    @pytest.mark.parametrize(
        "template_id", [s["template_id"] for s in STARTER_TEMPLATES]
    )
    def test_starter_trigger_has_a_real_emit_site(self, template_id):
        trigger = _start_trigger(template_id)
        needle = f'trigger_type="{trigger}"'
        components_dir = _REPO_ROOT / "components"
        assert components_dir.is_dir(), components_dir
        emitted = any(
            needle in path.read_text(encoding="utf-8", errors="ignore")
            for path in components_dir.rglob("*.py")
            if "/tests/" not in str(path)
        )
        assert emitted, f"no emit site for trigger_type={trigger!r} ({template_id})"
