from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import CustomUser, UserProfile

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False

@admin.register(CustomUser)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('username','first_name', 'last_name')}),
        (_('Permissions'), {'fields': ('is_active', 'is_verified', 'is_staff', 'is_onboard_complete', 'is_contributor', 'is_superuser',
                                       'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
    )
    list_display = ('email', 'id', 'first_name', 'last_name', 'is_staff', 'auth_provider', 'is_verified')
    search_fields = ('id', 'email', 'first_name', 'last_name')
    ordering = ('id',)
    inlines = (UserProfileInline, )
