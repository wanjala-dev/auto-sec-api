"""Coverage for feature flag evaluation and API exposure."""

import pytest
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError

from components.shared_platform.infrastructure.services.feature_flags import (
    evaluate_feature_flag,
    flags_for_context,
    is_feature_enabled,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]


def test_feature_flag_resolution_order_user_over_workspace_over_global_over_default(user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    flag = FeatureFlag.objects.create(key="demo.test_flag", default_enabled=False)

    # Default: off
    assert evaluate_feature_flag("demo.test_flag", user=user, workspace_id=str(workspace.id)).enabled is False

    # Global override: on
    FeatureFlagRule.objects.create(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL, enabled=True)
    result = evaluate_feature_flag("demo.test_flag", user=user, workspace_id=str(workspace.id))
    assert result.enabled is True
    assert result.source == "global_rule"

    # Workspace override: off
    FeatureFlagRule.objects.create(
        flag=flag,
        scope=FeatureFlagRule.Scope.WORKSPACE,
        workspace=workspace,
        enabled=False,
    )
    result = evaluate_feature_flag("demo.test_flag", user=user, workspace_id=str(workspace.id))
    assert result.enabled is False
    assert result.source == "workspace_rule"

    # User override: on
    FeatureFlagRule.objects.create(
        flag=flag,
        scope=FeatureFlagRule.Scope.USER,
        user=user,
        enabled=True,
    )
    result = evaluate_feature_flag("demo.test_flag", user=user, workspace_id=str(workspace.id))
    assert result.enabled is True
    assert result.source == "user_rule"


def test_feature_flag_scheduled_rules_are_ignored_until_active(user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    flag = FeatureFlag.objects.create(key="demo.scheduled", default_enabled=False)

    future = timezone.now() + timedelta(hours=1)
    FeatureFlagRule.objects.create(
        flag=flag,
        scope=FeatureFlagRule.Scope.GLOBAL,
        enabled=True,
        starts_at=future,
    )

    assert is_feature_enabled("demo.scheduled", user=user, workspace_id=str(workspace.id)) is False


def test_feature_flag_key_is_normalized_and_immutable():
    flag = FeatureFlag.objects.create(key="  Demo.Mixed_Case  ", default_enabled=False)
    assert flag.key == "demo.mixed_case"

    flag.description = "ok"
    flag.save()

    flag.key = "demo.renamed"
    with pytest.raises(ValidationError):
        flag.save()


def test_flags_for_context_returns_boolean_map(user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)

    FeatureFlag.objects.create(key="demo.a", default_enabled=False)
    FeatureFlag.objects.create(key="demo.b", default_enabled=True)

    data = flags_for_context(user=user, workspace_id=str(workspace.id))
    assert data["demo.a"] is False
    assert data["demo.b"] is True


def test_feature_flags_api_returns_flags(api_client, user_factory, workspace_factory):
    from django.urls import reverse

    user = user_factory()
    workspace = workspace_factory(owner=user)
    FeatureFlag.objects.create(key="demo.api", default_enabled=True)

    api_client.force_authenticate(user=user)
    response = api_client.get(f"{reverse('feature-flags')}?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data["workspace_id"] == str(workspace.id)
    assert response.data["flags"]["demo.api"] is True


def test_feature_flag_status_api_returns_single_flag(api_client, user_factory, workspace_factory):
    from django.urls import reverse

    user = user_factory()
    workspace = workspace_factory(owner=user)
    FeatureFlag.objects.create(key="demo.single", default_enabled=True)

    api_client.force_authenticate(user=user)
    response = api_client.get(f"{reverse('feature-flag', kwargs={'key': 'DEMO.SINGLE'})}?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data["key"] == "demo.single"
    assert response.data["enabled"] is True
    assert response.data["workspace_id"] == str(workspace.id)
