from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'recipient',
        'actor',
        'workspace',
        'notification_type',
        'verb',
        'is_read',
        'created_at',
    )
    list_filter = ('notification_type', 'is_read', 'workspace')
    search_fields = ('verb', 'metadata')
    autocomplete_fields = ('recipient', 'actor')
