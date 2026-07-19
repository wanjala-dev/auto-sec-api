from django.contrib import admin

from .models import Membership, Subscription, UserMembership


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("membership_type", "price", "slug")
    list_filter = ("membership_type",)
    search_fields = ("slug",)


@admin.register(UserMembership)
class UserMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "membership")
    list_filter = ("membership",)
    search_fields = ("user__email", "user__username")
    raw_id_fields = ("user", "membership")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user_membership", "active", "created")
    list_filter = ("active",)
    raw_id_fields = ("user_membership",)
