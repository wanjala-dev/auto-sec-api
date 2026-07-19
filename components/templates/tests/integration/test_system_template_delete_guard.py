"""System templates cannot be trashed — only workspace-owned ones. The gallery
hides the delete affordance; this guard is the backend enforcement so a direct
recycle-bin call can't remove a platform template from every tenant at once.

Ported to the Auto-Sec fork's ``security_report_template`` kind.
"""

from __future__ import annotations

import pytest

from components.templates.application.providers.template_soft_delete_provider import (
    get_template_soft_delete_adapters,
)
from infrastructure.persistence.security_templates.models import SecurityReportTemplate

pytestmark = pytest.mark.django_db


def _adapter():
    return next(a for a in get_template_soft_delete_adapters() if a.entity_type() == "security_report_template")


def _template(workspace=None, is_seeded=False):
    return SecurityReportTemplate.objects.create(
        workspace=workspace, name="T", category="Pentest", body_html="<p>x</p>", is_seeded=is_seeded
    )


class TestSystemTemplateGuard:
    def test_global_template_refuses_trash(self):
        template = _template(workspace=None)
        with pytest.raises(ValueError, match="System templates"):
            _adapter().soft_delete(str(template.id))
        template.refresh_from_db()
        assert template.is_deleted is False

    def test_seeded_template_refuses_trash(self):
        template = _template(workspace=None, is_seeded=True)
        with pytest.raises(ValueError, match="System templates"):
            _adapter().soft_delete(str(template.id))

    def test_workspace_template_trashes_and_restores(self, workspace_factory):
        ws = workspace_factory()
        template = _template(workspace=ws)
        adapter = _adapter()

        snapshot = adapter.soft_delete(str(template.id))
        template.refresh_from_db()
        assert template.is_deleted is True
        assert snapshot["workspace_id"] == str(ws.id)

        adapter.restore(str(template.id))
        template.refresh_from_db()
        assert template.is_deleted is False
