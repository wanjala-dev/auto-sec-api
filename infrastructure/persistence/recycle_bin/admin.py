from django.contrib import admin
from .models import RecycleBinEntry


@admin.register(RecycleBinEntry)
class RecycleBinEntryAdmin(admin.ModelAdmin):
    list_display = ('entity_type', 'entity_name', 'stage', 'deleted_at', 'workspace_id')
    list_filter = ('stage', 'entity_type')
    search_fields = ('entity_name', 'entity_id')
    readonly_fields = ('id', 'deleted_at')
