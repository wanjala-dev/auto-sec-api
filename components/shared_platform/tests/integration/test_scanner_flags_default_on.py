"""Scanner capabilities are ON by default — kill-switch posture, not entitlement.

The four scanner capability flags ship in Free
(docs/product/PRICING_PACKAGING_RECOMMENDATION_2026-08-08.md), so a fresh
workspace's first scan must never 403 on a flag an operator forgot to seed.
These tests lock the whole contract:

* the seed creates the four flags ``default_enabled=True`` and a fresh
  workspace resolves them ON with no rule rows at all (source=``default``);
* the kill-switch still works at every scope — an explicit WORKSPACE or GLOBAL
  disable rule beats the default (resolver ladder unchanged, ADR 0020 D0);
* the prod seed no longer dark-launches them, and it cleans up ITS OWN stale
  global disable rules from the pre-2026-08-08 policy while never touching an
  operator's rules;
* the backfill migration retro-fixes existing databases the same way; and
* the scan endpoints stop 403ing by flag for a brand-new workspace (they stay
  RBAC- and consent-gated — a flag being ON runs nothing without a connection).
"""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import override_settings

from components.shared_platform.cli.management.commands.seed_feature_flags import (
    PROD_DISABLE_NOTE,
    PROD_DISABLED_FLAGS,
)
from components.shared_platform.infrastructure.services.feature_flags import evaluate_feature_flag
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

pytestmark = [pytest.mark.integration, pytest.mark.django_db, pytest.mark.real_feature_flags]

SCANNER_FLAGS = (
    "feature.cloud_posture",
    "feature.container_security",
    "feature.code_security",
    "feature.vercel_posture",
)

_MIGRATION = import_module("infrastructure.persistence.core.migrations.0004_scanner_capabilities_default_on")


def _seed():
    call_command("seed_feature_flags", verbosity=0)


class TestSeedDefaultsOn:
    def test_fresh_workspace_resolves_scanner_capabilities_on_with_no_rules(self, workspace_factory):
        _seed()
        ws = workspace_factory()
        for key in SCANNER_FLAGS:
            flag = FeatureFlag.objects.get(key=key)
            assert flag.default_enabled is True, key
            evaluation = evaluate_feature_flag(key, workspace_id=str(ws.id))
            assert evaluation.enabled is True, key
            # No rule row involved — pure default. This is the exact regression
            # (403 until an operator hand-seeds a FeatureFlagRule) this locks out.
            assert evaluation.source == "default", key

    def test_scanner_flags_left_the_prod_disable_list(self):
        for key in SCANNER_FLAGS:
            assert key not in PROD_DISABLED_FLAGS, key

    def test_explicit_workspace_disable_rule_still_wins(self, workspace_factory):
        _seed()
        ws = workspace_factory()
        flag = FeatureFlag.objects.get(key="feature.code_security")
        FeatureFlagRule.objects.create(
            flag=flag,
            scope=FeatureFlagRule.Scope.WORKSPACE,
            workspace=ws,
            enabled=False,
            note="Operator opted this workspace out.",
        )
        evaluation = evaluate_feature_flag("feature.code_security", workspace_id=str(ws.id))
        assert evaluation.enabled is False
        assert evaluation.source == "workspace_rule"

    def test_global_disable_rule_is_still_a_break_glass_kill_switch(self, workspace_factory):
        _seed()
        ws = workspace_factory()
        flag = FeatureFlag.objects.get(key="feature.container_security")
        FeatureFlagRule.objects.create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            enabled=False,
            note="Operator break-glass.",
        )
        evaluation = evaluate_feature_flag("feature.container_security", workspace_id=str(ws.id))
        assert evaluation.enabled is False
        assert evaluation.source == "global_rule"


class TestProdSeedBehaviour:
    @override_settings(DEBUG=False)
    def test_prod_seed_does_not_dark_launch_scanner_capabilities(self, workspace_factory):
        _seed()
        ws = workspace_factory()
        for key in SCANNER_FLAGS:
            assert not FeatureFlagRule.objects.filter(flag__key=key, scope=FeatureFlagRule.Scope.GLOBAL).exists(), key
            assert evaluate_feature_flag(key, workspace_id=str(ws.id)).enabled is True, key
        # The flags that ARE still pre-GA keep their prod disable rules.
        for key in PROD_DISABLED_FLAGS:
            rule = FeatureFlagRule.objects.get(flag__key=key, scope=FeatureFlagRule.Scope.GLOBAL)
            assert rule.enabled is False
            assert rule.note == PROD_DISABLE_NOTE

    @override_settings(DEBUG=False)
    def test_prod_seed_removes_its_own_stale_disable_rules(self):
        _seed()
        # Simulate a prod DB seeded before 2026-08-08: the old policy's
        # seed-created global disable rule still present for a scanner flag.
        flag = FeatureFlag.objects.get(key="feature.code_security")
        FeatureFlagRule.objects.create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            enabled=False,
            note=PROD_DISABLE_NOTE,
        )
        _seed()
        assert not FeatureFlagRule.objects.filter(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL).exists()

    @override_settings(DEBUG=False)
    def test_prod_seed_never_touches_operator_rules(self, workspace_factory):
        _seed()
        ws = workspace_factory()
        flag = FeatureFlag.objects.get(key="feature.cloud_posture")
        FeatureFlagRule.objects.create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            enabled=False,
            note="Incident 2026-08-01: scanner runaway, operator kill-switch.",
        )
        _seed()
        assert FeatureFlagRule.objects.filter(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL).count() == 1
        assert evaluate_feature_flag("feature.cloud_posture", workspace_id=str(ws.id)).enabled is False


class TestBackfillMigration:
    """The data migration retro-fixes databases that predate the flip."""

    def _old_world(self):
        for key in SCANNER_FLAGS:
            FeatureFlag.objects.create(key=key, default_enabled=False)
        stale = FeatureFlagRule.objects.create(
            flag=FeatureFlag.objects.get(key="feature.code_security"),
            scope=FeatureFlagRule.Scope.GLOBAL,
            enabled=False,
            note=_MIGRATION.SEED_PROD_DISABLE_NOTE,
        )
        return stale

    def test_flips_defaults_and_drops_only_seed_created_disable_rules(self, workspace_factory):
        ws = workspace_factory()
        self._old_world()
        operator_rule = FeatureFlagRule.objects.create(
            flag=FeatureFlag.objects.get(key="feature.cloud_posture"),
            scope=FeatureFlagRule.Scope.GLOBAL,
            enabled=False,
            note="Operator kill-switch — must survive the backfill.",
        )
        explicit_off = FeatureFlagRule.objects.create(
            flag=FeatureFlag.objects.get(key="feature.container_security"),
            scope=FeatureFlagRule.Scope.WORKSPACE,
            workspace=ws,
            enabled=False,
            note="This workspace explicitly opted out.",
        )

        _MIGRATION.scanner_capabilities_default_on(django_apps, None)
        _MIGRATION.scanner_capabilities_default_on(django_apps, None)  # idempotent

        for key in SCANNER_FLAGS:
            assert FeatureFlag.objects.get(key=key).default_enabled is True, key
        # The seed-created stale disable rule is gone…
        assert not FeatureFlagRule.objects.filter(
            flag__key="feature.code_security", scope=FeatureFlagRule.Scope.GLOBAL
        ).exists()
        # …while explicit operator decisions survive and still win.
        assert FeatureFlagRule.objects.filter(pk=operator_rule.pk).exists()
        assert FeatureFlagRule.objects.filter(pk=explicit_off.pk).exists()
        assert evaluate_feature_flag("feature.cloud_posture", workspace_id=str(ws.id)).enabled is False
        assert evaluate_feature_flag("feature.container_security", workspace_id=str(ws.id)).enabled is False
        assert evaluate_feature_flag("feature.code_security", workspace_id=str(ws.id)).enabled is True

    def test_reverse_restores_default_off(self):
        self._old_world()
        _MIGRATION.scanner_capabilities_default_on(django_apps, None)
        _MIGRATION.scanner_capabilities_default_off(django_apps, None)
        for key in SCANNER_FLAGS:
            assert FeatureFlag.objects.get(key=key).default_enabled is False, key


class TestScanEndpointsNotFlagGatedByDefault:
    """A fresh workspace's scan surface must not 403 by flag — only by RBAC/consent."""

    def test_container_scan_passes_the_flag_gate_for_a_fresh_workspace(self, api_client, workspace_factory):
        _seed()
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        # A deliberately invalid image stops the request at validation — AFTER
        # the flag gate, BEFORE any dispatch. 400 proves the gate opened.
        resp = api_client.post(
            f"/container-security/workspaces/{ws.id}/scan/",
            {"image": "not a valid image ref !!"},
            format="json",
        )
        assert resp.status_code == 400, resp.data
        assert resp.data["error"] == "invalid_image"

    def test_repo_scan_is_consent_gated_not_flag_gated(self, api_client, workspace_factory):
        _seed()
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        # No VcsConnection exists — the honest refusal is the ADR 0019 consent
        # gate (allowlist fail-closed), never the feature flag.
        resp = api_client.post(
            f"/code-security/workspaces/{ws.id}/scan/",
            {"repo": "acme/app"},
            format="json",
        )
        assert resp.status_code in (400, 403), resp.data
        assert resp.data["error"] != "feature_disabled"

    def test_non_member_is_still_forbidden(self, api_client, workspace_factory, user_factory):
        _seed()
        ws = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(outsider)
        resp = api_client.post(
            f"/container-security/workspaces/{ws.id}/scan/",
            {"image": "alpine:3.20"},
            format="json",
        )
        assert resp.status_code == 403, resp.data
        assert resp.data["error"] == "forbidden"
