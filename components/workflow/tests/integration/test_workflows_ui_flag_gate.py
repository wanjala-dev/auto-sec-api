"""Coverage for the feature.workflows_ui scope-freeze gate.

See docs/plans/GO_TO_MARKET_PLAN.md §6 and
docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 4.

When feature.workflows_ui is off (prod default), every end-user workflow
UI surface (templates, workflows, bindings, runs, triggers) returns 403.
The workflow engine, Celery task runner, and the internal dispatcher
(``emit_workflow_event``) remain fully available — internal automations
still run.
"""

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]


FLAG_KEY = "feature.workflows_ui"


def _set_flag(enabled: bool) -> None:
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": True, "description": "test-seeded"},
    )
    if enabled:
        FeatureFlagRule.objects.filter(
            flag=flag, scope=FeatureFlagRule.Scope.GLOBAL
        ).delete()
    else:
        FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            defaults={"enabled": False, "note": "gate test"},
        )
    bump_feature_flags_version()


# Workflow URLs are mounted at /workspaces/workflows/*
_BASE = "/workspaces/workflows"


# ---------------------------------------------------------------------------
# Flag off ⇒ 403 on every workflow UI surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", f"{_BASE}/workflow-templates/"),
        ("get", f"{_BASE}/workflows/"),
        ("get", f"{_BASE}/workflow-bindings/"),
        ("get", f"{_BASE}/workflow-runs/"),
        ("get", f"{_BASE}/workflow-triggers/"),
    ],
)
def test_workflow_ui_blocked_when_flag_off(
    api_client, user_factory, workspace_factory, method, url
):
    _set_flag(False)
    user = user_factory()
    workspace_factory(owner=user)
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 403, (
        f"{method.upper()} {url} should 403 when feature.workflows_ui is off "
        f"(got {response.status_code})"
    )


# ---------------------------------------------------------------------------
# Flag on ⇒ permission layer permits
# ---------------------------------------------------------------------------


def test_workflow_templates_permission_passes_when_flag_on(
    api_client, user_factory, workspace_factory
):
    """Flag on ⇒ RequiresFeatureFlag permits. IsOrgOwnerOrMember still
    applies, so we pass ?workspace_id=<uuid> so that permission resolves
    the workspace and accepts the owner. If RequiresFeatureFlag were
    denying, the response would still be 403 even with the workspace
    identifier supplied.
    """
    _set_flag(True)
    user = user_factory()
    workspace = workspace_factory(owner=user)
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)

    response = api_client.get(
        f"{_BASE}/workflow-templates/?workspace_id={workspace.id}"
    )

    assert response.status_code != 403


# ---------------------------------------------------------------------------
# Internal dispatcher remains callable regardless of flag state
# ---------------------------------------------------------------------------


def test_internal_dispatcher_unaffected_by_flag(workspace_factory, user_factory):
    """The engine's internal emit_workflow_event entrypoint must not check
    the UI flag — internal automations keep running when the UI is gated.
    """
    _set_flag(False)
    user = user_factory()
    workspace = workspace_factory(owner=user)

    from components.workflow.infrastructure.adapters.dispatcher import (
        emit_workflow_event,
    )

    event = emit_workflow_event(
        workspace_id=str(workspace.id),
        source_type="test",
        trigger_type="test.trigger",
        payload={"sample": True},
    )

    assert event is not None
    assert event.trigger_type == "test.trigger"
