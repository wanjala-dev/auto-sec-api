from django.contrib import admin

from infrastructure.persistence.tenancy.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("subdomain", "name", "isolation_mode", "db_alias", "is_active", "created_at")
    list_filter = ("isolation_mode", "is_active")
    search_fields = ("subdomain", "name", "db_alias")
