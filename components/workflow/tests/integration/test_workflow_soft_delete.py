"""The workflow soft-delete adapter moves a workflow to the recycle bin and back.

Delete (recycle bin) is distinct from Archive: Delete sets ``is_deleted`` and is
restorable via the shared recycle-bin registry; Archive only flips status.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.workspaces.workflows.models import Workflow

pytestmark = [pytest.mark.django_db]


def _workflow(workspace, **kw):
    return Workflow.objects.create(
        workspace=workspace, name="To delete", goal="general",
        status="published", graph={"nodes": [], "edges": []}, **kw,
    )


class TestWorkflowSoftDeleteAdapter:
    def _adapter(self):
        from components.workflow.application.providers.workflow_soft_delete_provider import (
            get_workflow_soft_delete_provider,
        )
        return get_workflow_soft_delete_provider().adapter()

    def test_entity_type(self):
        assert self._adapter().entity_type() == "workflow"

    def test_soft_delete_then_restore(self, workspace_factory):
        wf = _workflow(workspace_factory())
        adapter = self._adapter()

        snapshot = adapter.soft_delete(str(wf.id))
        wf.refresh_from_db()
        assert wf.is_deleted is True
        assert snapshot["name"] == "To delete"
        assert snapshot["id"] == str(wf.id)

        adapter.restore(str(wf.id))
        wf.refresh_from_db()
        assert wf.is_deleted is False

    def test_hard_delete_removes_row(self, workspace_factory):
        wf = _workflow(workspace_factory())
        wf_id = wf.id
        self._adapter().hard_delete(str(wf_id))
        assert not Workflow.objects.filter(id=wf_id).exists()


class TestRegisteredInRecycleBin:
    def test_workflow_adapter_resolvable_from_registry(self, workspace_factory):
        from components.recycle_bin.application.providers.recycle_bin_provider import (
            get_recycle_bin_service,
        )
        # Building the service wires every registered soft-delete adapter; the
        # workflow adapter must resolve (else Delete would 500 at runtime).
        service = get_recycle_bin_service()
        adapter = service.provider.get_adapter("workflow")
        assert adapter.entity_type() == "workflow"
