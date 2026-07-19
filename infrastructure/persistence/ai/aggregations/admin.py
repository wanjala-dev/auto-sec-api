from django.contrib import admin

from infrastructure.persistence.ai.aggregations.models import WorkspaceAIUsage


@admin.register(WorkspaceAIUsage)
class WorkspaceAIUsageAdmin(admin.ModelAdmin):
    list_display = (
        "workspace_id",
        "daily_messages_sent",
        "daily_window_start",
        "monthly_tokens_used",
        "monthly_window_start",
        "last_message_at",
    )
    list_filter = ("daily_window_start", "monthly_window_start")
    search_fields = ("workspace__title", "workspace__id")
    readonly_fields = ("updated_at",)
    raw_id_fields = ("workspace",)
