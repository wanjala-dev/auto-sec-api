"""Unit tests: gallery summaries carry a thumbnail preview source (task #13)."""

from __future__ import annotations

from components.templates.domain.template_kind import TEMPLATE_KINDS, TemplateKindSpec
from components.templates.infrastructure.adapters.configurable_template_source_adapter import (
    ConfigurableTemplateSourceAdapter,
)


class _Row:
    def __init__(self, metadata=None, body_html=""):
        self.metadata = metadata
        self.body_html = body_html


_SPEC = TemplateKindSpec(
    id="writing_template",
    label="Writing templates",
    model_label="content.WritingTemplate",
    preview_layout_field="metadata",
    preview_body_field="body_html",
)


class TestPreviewSource:
    def test_design_layout_wins(self):
        layout = {"version": 5, "blocks": [{"kind": "text", "payload": {"html": "<p>x</p>"}}]}
        row = _Row(metadata={"layout": layout}, body_html="<p>fallback</p>")
        assert ConfigurableTemplateSourceAdapter._preview(row, _SPEC) == {"layout": layout}

    def test_prose_body_falls_back_trimmed(self):
        row = _Row(metadata={}, body_html="<p>" + "x" * 5000 + "</p>")
        preview = ConfigurableTemplateSourceAdapter._preview(row, _SPEC)
        assert "body_html" in preview
        assert len(preview["body_html"]) == 4000

    def test_empty_layout_blocks_fall_back_to_body(self):
        row = _Row(metadata={"layout": {"version": 5, "blocks": []}}, body_html="<p>b</p>")
        assert ConfigurableTemplateSourceAdapter._preview(row, _SPEC) == {"body_html": "<p>b</p>"}

    def test_kinds_without_preview_fields_return_none(self):
        spec = TEMPLATE_KINDS["workflow_template"]
        row = _Row(metadata={"layout": {"blocks": [1]}}, body_html="<p>b</p>")
        assert ConfigurableTemplateSourceAdapter._preview(row, spec) is None

    def test_security_spec_registers_preview_body(self):
        spec = TEMPLATE_KINDS["security_report_template"]
        assert spec.preview_body_field == "body_html"
        assert spec.preview_layout_field is None
