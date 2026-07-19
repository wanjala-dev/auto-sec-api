"""The template catalog endpoint must return EVERY template, unpaginated.

The builder's template picker is a selector — it needs the complete catalog. The
global DRF pagination (PAGE_SIZE=10) silently truncated the list once there were
more than 10 system templates: ``sponsor`` landed on page 2 and never reached the
client, which then fell back to a stale local stub graph that failed Publish.
``WorkflowTemplateViewSet.pagination_class = None`` fixes that; this test locks it
so a future pagination default can't silently re-truncate the picker.
"""

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.workspaces.workflows.models import WorkflowTemplate

pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]

_BASE = "/workspaces/workflows"
FLAG_KEY = "feature.workflows_ui"


def _enable_flag() -> None:
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": True, "description": "test-seeded"},
    )
    FeatureFlagRule.objects.filter(
        flag=flag, scope=FeatureFlagRule.Scope.GLOBAL
    ).delete()
    bump_feature_flags_version()


def _minimal_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "config": {}},
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [{"id": "e0", "from": "start", "to": "end"}],
    }


def _seed_system_templates(n: int) -> None:
    for i in range(n):
        WorkflowTemplate.objects.create(
            id=f"sys-tmpl-{i:02d}",
            label=f"System Template {i:02d}",
            description="seed",
            category="campaign",
            version="1",
            is_system=True,
            workspace=None,
            default_graph=_minimal_graph(),
        )


def test_catalog_returns_all_templates_beyond_page_size(
    api_client, user_factory, workspace_factory
):
    """With more system templates than PAGE_SIZE (10), the endpoint still
    returns every one — no pagination cap, no envelope."""
    _enable_flag()
    # 15 > global PAGE_SIZE (10): a paginated response would drop 5.
    _seed_system_templates(15)

    user = user_factory()
    workspace = workspace_factory(owner=user)
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get(
        f"{_BASE}/workflow-templates/?workspace_id={workspace.id}"
    )

    assert response.status_code == 200, response.status_code
    # Unpaginated => a plain list, not a {"count", "results"} envelope.
    assert isinstance(response.data, list), (
        f"expected an un-paginated list, got {type(response.data)} "
        f"({list(response.data)[:3] if hasattr(response.data, '__iter__') else response.data})"
    )
    returned_ids = {t["id"] for t in response.data}
    seeded_ids = {f"sys-tmpl-{i:02d}" for i in range(15)}
    assert seeded_ids <= returned_ids, (
        f"catalog truncated — missing {sorted(seeded_ids - returned_ids)}"
    )
