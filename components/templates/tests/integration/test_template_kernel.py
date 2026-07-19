"""Integration tests for the Template Kernel against the Auto-Sec fork kinds.

Covers the registry (fan-out + unknown kind), the generic source adapter reading
the ``security_report_template`` kind via its spec, and the recycle-bin delete
guard (system templates are protected; workspace-owned templates trash + restore).
"""

from __future__ import annotations

import pytest

from components.shared_kernel.domain.errors import ValidationError
from components.templates.application.providers.template_registry_provider import (
    TemplateRegistry,
)
from components.templates.application.providers.template_soft_delete_provider import (
    get_template_soft_delete_adapters,
)
from components.templates.domain.errors import UnknownTemplateKind
from components.templates.domain.template_kind import TEMPLATE_KINDS
from components.templates.infrastructure.adapters.configurable_template_source_adapter import (
    ConfigurableTemplateSourceAdapter,
)
from infrastructure.persistence.security_templates.models import SecurityReportTemplate


def _build_registry() -> TemplateRegistry:
    registry = TemplateRegistry()
    for spec in TEMPLATE_KINDS.values():
        registry.register(ConfigurableTemplateSourceAdapter(spec))
    return registry


class TestRegistry:
    def test_both_fork_kinds_registered(self):
        registry = _build_registry()
        assert registry.kinds() == ["security_report_template", "workflow_template"]

    def test_unknown_kind_raises(self):
        with pytest.raises(UnknownTemplateKind):
            _build_registry().source_for("nope")


@pytest.mark.django_db
class TestSecurityReportSource:
    def test_lists_system_templates(self):
        SecurityReportTemplate.objects.create(name="Pentest Report", category="Pentest", is_seeded=True, workspace=None)
        summaries = _build_registry().list_templates(workspace_id=None, kind="security_report_template")
        row = next(s for s in summaries if s.name == "Pentest Report")
        assert row.scope == "system"
        assert row.is_system is True
        assert row.category == "Pentest"

    def test_body_html_drives_preview(self):
        SecurityReportTemplate.objects.create(
            name="RCA", category="RCA", body_html="<h1>RCA</h1>", is_seeded=True, workspace=None
        )
        [row] = [
            s
            for s in _build_registry().list_templates(workspace_id=None, kind="security_report_template")
            if s.name == "RCA"
        ]
        assert row.preview == {"body_html": "<h1>RCA</h1>"}

    def test_workspace_sees_own_plus_system(self, workspace_factory):
        ws = workspace_factory()
        SecurityReportTemplate.objects.create(name="Sys", is_seeded=True, workspace=None)
        SecurityReportTemplate.objects.create(name="Mine", workspace=ws)
        summaries = _build_registry().list_templates(workspace_id=str(ws.id), kind="security_report_template")
        by_name = {s.name: s for s in summaries}
        assert by_name["Sys"].scope == "system"
        assert by_name["Mine"].scope == "workspace"


@pytest.mark.django_db
class TestDeleteGuard:
    def _adapter(self):
        return next(a for a in get_template_soft_delete_adapters() if a.entity_type() == "security_report_template")

    def test_system_template_cannot_be_trashed(self):
        tpl = SecurityReportTemplate.objects.create(name="Sys", is_seeded=True, workspace=None)
        with pytest.raises(ValidationError):
            self._adapter().soft_delete(str(tpl.id))
        tpl.refresh_from_db()
        assert tpl.is_deleted is False

    def test_workspace_template_trashes_and_restores(self, workspace_factory):
        ws = workspace_factory()
        tpl = SecurityReportTemplate.objects.create(name="Mine", workspace=ws)
        adapter = self._adapter()
        snapshot = adapter.soft_delete(str(tpl.id))
        assert snapshot["kind"] == "security_report_template"
        tpl.refresh_from_db()
        assert tpl.is_deleted is True
        adapter.restore(str(tpl.id))
        tpl.refresh_from_db()
        assert tpl.is_deleted is False
