from django.contrib import admin

from .models import Invitation, Team, TeamMembership

# PlanAdmin relocated with the Plan model to the subscription app —
# see infrastructure/persistence/subscription/admin.py.


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    fields = ("user", "role", "status")
    raw_id_fields = ("user",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "status", "kind", "privacy", "created_by", "created_at")
    list_filter = ("status", "kind", "privacy")
    search_fields = ("title", "workspace__workspace_name", "created_by__email")
    raw_id_fields = ("workspace", "created_by")
    date_hierarchy = "created_at"
    inlines = [TeamMembershipInline]


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("team", "user", "role", "status")
    list_filter = ("role", "status")
    search_fields = ("team__title", "user__email")
    raw_id_fields = ("team", "user")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "team", "workspace", "status", "date_sent")
    list_filter = ("status",)
    search_fields = ("email", "team__title", "workspace__workspace_name")
    raw_id_fields = ("team", "workspace")
    date_hierarchy = "date_sent"
