"""The workflow ``enrich`` node — resolve an IOC from the run context, enrich, and
write the corroborated verdict as the step output (mocked provider, no network)."""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.domain.value_objects.enrichment_result import (
    EnrichmentResult,
    EnrichmentVerdict,
)
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind
from components.workflow.infrastructure.adapters.node_actions import (
    _execute_enrich,
    execute_node_action,
)
from infrastructure.persistence.workspaces.workflows.models import Workflow, WorkflowRun

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_ALL = "components.integrations.application.providers.ioc_enrichment_provider.IocEnrichmentProvider.enrich_all"

_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "title": "Start", "config": {"triggerType": "finding_high"}},
        {"id": "end", "type": "end", "title": "End", "config": {}},
    ],
    "edges": [{"id": "e0", "from": "start", "to": "end"}],
}


def _run(ws, payload):
    wf = Workflow.objects.create(workspace=ws, name="enrich-test", goal="general", status="draft", graph=_GRAPH)
    return WorkflowRun.objects.create(
        workflow=wf,
        workflow_version=wf.version,
        status=WorkflowRun.Status.QUEUED,
        trigger_type="finding_high",
        trigger_payload=payload,
        target_type="finding",
        target_id="task-1",
    )


def _malicious(ip="8.8.8.8"):
    return [
        EnrichmentResult(
            provider="virustotal",
            indicator=Indicator(IndicatorKind.IP, ip),
            verdict=EnrichmentVerdict.MALICIOUS,
            score=90,
            positives=10,
        )
    ]


class TestEnrichNode:
    def test_resolves_indicator_from_trigger_and_writes_verdict(self, workspace_factory):
        run = _run(workspace_factory(), {"ip": "8.8.8.8", "severity": "high"})
        with mock.patch(_ALL, return_value=_malicious()):
            out = _execute_enrich(run, {"type": "enrich"}, {"indicator_path": "trigger.ip"})
        assert out["status"] == "enriched"
        assert out["indicator"] == "8.8.8.8" and out["kind"] == "ip"
        assert out["verdict"] == "malicious" and out["score"] == 90  # branchable as steps.<enrich>.verdict

    def test_resolves_from_top_level_payload_key(self, workspace_factory):
        run = _run(workspace_factory(), {"ip": "8.8.8.8"})
        with mock.patch(_ALL, return_value=_malicious()):
            out = _execute_enrich(run, {"type": "enrich"}, {"indicator_path": "ip"})
        assert out["verdict"] == "malicious"

    def test_literal_value(self, workspace_factory):
        run = _run(workspace_factory(), {})
        with mock.patch(_ALL, return_value=_malicious("1.2.3.4")):
            out = _execute_enrich(run, {"type": "enrich"}, {"value": "1.2.3.4"})
        assert out["indicator"] == "1.2.3.4"

    def test_no_resolvable_indicator_skips(self, workspace_factory):
        run = _run(workspace_factory(), {"severity": "high"})  # no ip in the payload
        out = _execute_enrich(run, {"type": "enrich"}, {"indicator_path": "trigger.ip"})
        assert out["status"] == "skipped"

    def test_dispatched_via_execute_node_action(self, workspace_factory):
        # Registered in _EXECUTORS → the walker runs it as an action node.
        run = _run(workspace_factory(), {"ip": "8.8.8.8"})
        with mock.patch(_ALL, return_value=_malicious()):
            out = execute_node_action(run, {"type": "enrich"}, {"indicator_path": "ip"})
        assert out["verdict"] == "malicious"
