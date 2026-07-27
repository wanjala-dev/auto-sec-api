from django.contrib import admin

from infrastructure.persistence.response.models import ResponseActionExecution


@admin.register(ResponseActionExecution)
class ResponseActionExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "dry_run", "workspace", "requested_at")
    list_filter = ("status", "dry_run", "kind")
    search_fields = ("finding_fingerprint", "id")
    readonly_fields = ("created_at", "updated_at")
