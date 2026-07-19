from __future__ import annotations

from django.contrib import admin

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


class FeatureFlagRuleInline(admin.TabularInline):
    """Per-workspace / per-user overrides, editable from the flag page itself.

    The flag's own ``default_enabled`` is the GLOBAL default — flipping it on a
    prod-disabled flag enables the feature for EVERY workspace (a GTM
    scope-freeze violation). To turn a gated feature on for one customer, add a
    rule here: scope=workspace, pick the workspace, enabled=True. Resolution
    order is user → workspace → global → default, so the rule wins.
    """

    model = FeatureFlagRule
    extra = 0
    raw_id_fields = ("workspace", "user", "updated_by")
    fields = ("scope", "enabled", "workspace", "user", "starts_at", "ends_at", "note")


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("key", "default_enabled", "updated_at")
    list_filter = ("default_enabled",)
    search_fields = ("key",)
    ordering = ("key",)
    inlines = [FeatureFlagRuleInline]


@admin.register(FeatureFlagRule)
class FeatureFlagRuleAdmin(admin.ModelAdmin):
    list_display = ("flag", "scope", "enabled", "workspace", "user", "starts_at", "ends_at", "updated_at")
    list_filter = ("scope", "enabled")
    search_fields = ("flag__key", "note", "workspace__workspace_name", "user__email", "user__username")
    # Use raw_id_fields to avoid requiring search_fields on related admin configs.
    raw_id_fields = ("flag", "workspace", "user", "updated_by")
    ordering = ("flag__key", "scope", "-updated_at")
